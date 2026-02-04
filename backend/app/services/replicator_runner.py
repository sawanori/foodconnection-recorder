"""
サイト複製ランナー

複製ジョブの全体フローを制御します。
フォルダ内のスクリーンショット画像からHTML/CSS/JSを生成します。
"""
import asyncio
import logging
import os
import glob
from typing import Optional
from datetime import datetime
from sqlalchemy import select

from app.database import get_session
from app.models import ReplicationJobModel, ReplicationStatus
from app.config import settings
from app.services.replicator import create_image_generator, MultiSectionGenerator
from app.services.replicator.base_image_generator import ImageGenerationError
from app.services.replicator.design_extractor import DesignExtractor

logger = logging.getLogger(__name__)

# 同時実行数制限
MAX_CONCURRENT_JOBS = 2
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


class ReplicatorRunner:
    """サイト複製ランナークラス"""

    def __init__(self, model_type: str = None):
        """
        Args:
            model_type: 使用するモデル ("claude" または "gemini")
                        Noneの場合は settings.IMAGE_GENERATOR_MODEL を使用
        """
        if model_type is None:
            model_type = settings.IMAGE_GENERATOR_MODEL
        self.model_type = model_type
        self.image_generator = create_image_generator(model_type)
        self.extractor = DesignExtractor()
        logger.info(f"Using image generator: {self.image_generator.get_model_name()}")

    async def run(self, job_id: str):
        """
        複製ジョブを実行

        Args:
            job_id: ジョブID
        """
        async with _semaphore:
            await self._execute(job_id)

    async def _execute(self, job_id: str):
        """ジョブ実行の本体"""
        logger.info(f"Starting replication job: {job_id}")

        try:
            # Phase 1: 画像読み込み（スクレイピングの代わり）
            await self._update_status(job_id, ReplicationStatus.SCRAPING)
            image_path = await self._find_screenshot(job_id)
            html_content = await self._read_html_file(job_id)
            video_path = await self._find_video_file(job_id)

            # URL情報読み込み（Phase 2で追加）
            source_url = await self._read_url_file(job_id, image_path)

            # デザイン抽出
            logger.info("Extracting design tokens...")
            if html_content:
                design_tokens = self.extractor.extract_from_html(html_content)
            else:
                design_tokens = self.extractor.extract_from_image(image_path)
            logger.info(f"Design tokens: {design_tokens}")

            # Phase 2: 生成
            await self._update_status(job_id, ReplicationStatus.GENERATING)

            # 画像サイズをチェックして生成モードを決定
            from PIL import Image
            img = Image.open(image_path)
            width, height = img.size
            img.close()
            
            is_full_page = height > width * 2.5 # 閾値を少し緩和

            generated_code = {}

            # 常に画像ベースで生成（HTMLは使わない）
            if is_full_page:
                # フルページ + HTMLなし：分割生成
                section_target_height = 1800
                num_sections = max(3, min(8, (height + section_target_height - 1) // section_target_height))
                logger.info(f"Full page without HTML ({width}x{height}), using multi-section generation with {num_sections} sections")
                multi_gen = MultiSectionGenerator(self.image_generator, num_sections=num_sections)
                generated_code = await self._generate_multi_section(
                    multi_gen, image_path, job_id, html_content=None, design_tokens=design_tokens, video_path=video_path
                )
            else:
                # 通常サイズ + HTMLなし：画像のみから生成
                logger.info("Normal page size + No HTML source, generating from image only")
                generated_code = await self._generate_from_image(
                    image_path,
                    job_id,
                    html_content=None,
                    video_path=video_path,
                    design_tokens=design_tokens
                )

            # 初期保存
            output_dir = await self._save_files(job_id, generated_code)
            logger.info(f"Initial files generated in: {output_dir}")

            # リファインメント: 元の画像と比較して改善
            logger.info("Starting refinement process to match original design...")
            try:
                refined_code = await self._refine_generated_code(
                    job_id,
                    image_path,
                    generated_code,
                    output_dir,
                    source_url=source_url  # Phase 2: URL情報を渡す
                )
                if refined_code:
                    # 改善されたコードで上書き保存
                    await self._save_files(job_id, refined_code)
                    logger.info(f"Refinement completed successfully")
            except Exception as e:
                logger.warning(f"Refinement failed, using original generation: {e}")

            # 完了 - 部分的成功のチェック
            if '_metadata' in generated_code and generated_code['_metadata'].get('failed_sections'):
                failed = generated_code['_metadata']['failed_sections']
                warning_msg = f"一部のセクション生成に失敗しました: {failed}"
                await self._update_status(job_id, ReplicationStatus.COMPLETED_WITH_WARNINGS, warnings=warning_msg)
                logger.warning(f"Job {job_id}: {warning_msg}")
            else:
                await self._update_status(job_id, ReplicationStatus.COMPLETED)
                logger.info(f"Replication job completed: {job_id}")

        except ImageGenerationError as e:
            logger.error(f"Replication job failed: {job_id} - {e}")
            await self._update_status(job_id, ReplicationStatus.FAILED, str(e))
        except Exception as e:
            logger.exception(f"Unexpected error in replication job: {job_id}")
            await self._update_status(job_id, ReplicationStatus.FAILED, str(e))

    async def _find_screenshot(self, job_id: str) -> str:
        """
        入力フォルダからスクリーンショット画像を検索

        検索順序:
        1. screenshots/サブフォルダ（優先）
        2. 入力フォルダ直下（後方互換性）
        3. 再帰検索（フォールバック）

        Args:
            job_id: ジョブID

        Returns:
            スクリーンショット画像のパス

        Raises:
            ImageGenerationError: 画像が見つからない場合
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            input_folder = job.input_folder

        # パターン1: screenshots/サブフォルダから検索（優先）
        png_files = glob.glob(os.path.join(input_folder, "screenshots", "*.png"))

        # パターン2: 直下から検索（後方互換性）
        if not png_files:
            png_files = glob.glob(os.path.join(input_folder, "*.png"))
            if png_files:
                logger.info("Found PNG files in root folder (legacy structure)")

        # パターン3: 再帰検索（フォールバック）
        if not png_files:
            png_files = glob.glob(os.path.join(input_folder, "**", "*.png"), recursive=True)
            if png_files:
                logger.info("Found PNG files via recursive search")

        if not png_files:
            raise ImageGenerationError(
                f"No PNG files found in: {input_folder}\n"
                f"Searched: screenshots/, root, and subdirectories"
            )

        # "_screenshot"を含むファイルを優先
        screenshot_files = [f for f in png_files if "_screenshot" in os.path.basename(f)]
        if screenshot_files:
            image_path = screenshot_files[0]
        else:
            image_path = png_files[0]

        logger.info(f"Found screenshot: {image_path}")
        return image_path

    async def _read_html_file(self, job_id: str) -> Optional[str]:
        """
        入力フォルダからHTMLファイルを検索して内容を読み込む
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            input_folder = job.input_folder

        # _source.html を優先検索
        html_files = glob.glob(os.path.join(input_folder, "*_source.html"))
        if not html_files:
            html_files = glob.glob(os.path.join(input_folder, "*.html"))

        if not html_files:
            logger.info("No HTML source file found.")
            return None

        html_path = html_files[0]
        logger.info(f"Found HTML source: {html_path}")
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to read HTML file: {e}")
            return None

    async def _find_video_file(self, job_id: str) -> Optional[str]:
        """
        入力フォルダから動画ファイルを検索

        検索順序:
        1. videos/サブフォルダ（優先）
        2. 入力フォルダ直下（後方互換性）

        Returns:
            動画ファイルのパス、見つからない場合はNone
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            input_folder = job.input_folder

        # パターン1: videos/サブフォルダから.webmを検索（優先）
        webm_files = glob.glob(os.path.join(input_folder, "videos", "*.webm"))

        # パターン2: 直下から.webmを検索（後方互換性）
        if not webm_files:
            webm_files = glob.glob(os.path.join(input_folder, "*.webm"))
            if webm_files:
                logger.info("Found WEBM files in root folder (legacy structure)")

        if webm_files:
            logger.info(f"Found video: {webm_files[0]}")
            return webm_files[0]

        # パターン3: videos/サブフォルダから.mp4を検索
        mp4_files = glob.glob(os.path.join(input_folder, "videos", "*.mp4"))

        # パターン4: 直下から.mp4を検索
        if not mp4_files:
            mp4_files = glob.glob(os.path.join(input_folder, "*.mp4"))

        if mp4_files:
            logger.info(f"Found video: {mp4_files[0]}")
            return mp4_files[0]

        logger.info("No video file found.")
        return None

    async def _read_url_file(self, job_id: str, screenshot_path: str) -> Optional[str]:
        """
        スクリーンショットに対応するURL情報ファイルを読み込む

        検索順序:
        1. FireShotファイル名からURL抽出（[domain.com]形式）
        2. {base_name}_url.txt（録画ファイルに対応）
        3. source_url.txt（レガシー形式）
        4. DB保存されたsource_url（フォールバック）

        Args:
            job_id: ジョブID
            screenshot_path: 見つかったスクリーンショットのパス

        Returns:
            URL文字列、見つからない場合はNone
        """
        import re

        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            input_folder = job.input_folder

        # スクリーンショットのファイル名からベース名を取得
        # 例: shop1_screenshot.png → shop1
        screenshot_basename = os.path.basename(screenshot_path)

        # FireShotファイル名からURLを抽出（[domain.com]形式）
        # 例: "FireShot Capture 011 - タイトル - [www.example.com].png"
        fireshot_pattern = r'\[([^\]]+\.[^\]]+)\]'
        fireshot_match = re.search(fireshot_pattern, screenshot_basename)
        if fireshot_match:
            domain = fireshot_match.group(1)
            extracted_url = f"https://{domain}"
            logger.info(f"Extracted URL from FireShot filename: {extracted_url}")
            return extracted_url

        base_name = screenshot_basename.replace("_screenshot.png", "").replace(".png", "")

        # 対応するURL情報ファイルを検索
        url_file_patterns = [
            os.path.join(input_folder, f"{base_name}_url.txt"),  # 優先
            os.path.join(input_folder, "source_url.txt"),        # レガシー
        ]

        for url_file_path in url_file_patterns:
            if not os.path.exists(url_file_path):
                continue

            try:
                with open(url_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # URL=... の形式をパース
                for line in content.split('\n'):
                    if line.startswith('URL='):
                        url = line.replace('URL=', '').strip()
                        logger.info(f"Found source URL from file: {url}")
                        return url

                # レガシー形式（1行目がURL）にも対応
                lines = content.strip().split('\n')
                if lines and lines[0].startswith('http'):
                    logger.info(f"Found source URL (legacy format): {lines[0]}")
                    return lines[0]

            except Exception as e:
                logger.warning(f"Failed to read URL file {url_file_path}: {e}")
                continue

        # ファイルから見つからない場合、DBから取得（フォールバック）
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            if job.source_url:
                logger.info(f"Using source URL from database: {job.source_url}")
                return job.source_url

        logger.info("No URL info found (file or database)")
        return None

    async def _reconstruct_from_html(
        self,
        image_path: str,
        html_content: str,
        video_path: str = None,
        design_tokens: dict = None
    ) -> dict:
        """
        画像+動画からサイトを生成（HTMLは参考程度）

        シンプルに画像を見てHTML/CSS/JSを生成する方式。
        元HTMLに依存せず、AIが見た目を再現する。

        Args:
            image_path: スクリーンショット画像のパス
            html_content: 元のHTMLソース（参考情報として渡すが、主に画像から生成）
            video_path: 録画動画のパス
            design_tokens: デザイントークン

        Returns:
            {"html": "...", "css": "...", "js": "..."}
        """
        logger.info(f"Generating from image + video (HTML as reference only)")
        logger.info(f"  Image: {image_path}")
        logger.info(f"  Video: {video_path}")
        logger.info(f"  Design tokens: {bool(design_tokens)}")

        # 画像ベースで生成（HTMLは渡さない = AIが自由に生成）
        return await self.image_generator.generate_from_image(
            image_path,
            html_content=None,  # HTMLを渡さない
            video_path=video_path,
            design_tokens=design_tokens
        )

    # 以前の _generate_css_js_only と _prepare_html_with_links は削除または非推奨
    # (コードの綺麗さのため、ここでは削除扱いとし、上記の実装のみにする)

    async def _generate_from_image(
        self,
        image_path: str,
        job_id: str = None,
        html_content: str = None,
        video_path: str = None,
        design_tokens: dict = None
    ) -> dict:
        """画像からコード生成（フルページの場合は分割生成）"""
        from PIL import Image

        # 画像サイズを確認
        img = Image.open(image_path)
        width, height = img.size
        img.close()

        # フルページ（高さが幅の3倍以上）の場合は分割生成
        if height > width * 3:
            # 動的に分割数を計算（1セクションあたり約1800px目安）
            section_target_height = 1800
            num_sections = max(3, min(8, (height + section_target_height - 1) // section_target_height))
            logger.info(f"Full page detected ({width}x{height}), using multi-section generation with {num_sections} sections")

            # ステータス更新
            multi_gen = MultiSectionGenerator(self.image_generator, num_sections=num_sections)

            # カスタム生成（ステータス更新付き）
            return await self._generate_multi_section(
                multi_gen, image_path, job_id, html_content=html_content, design_tokens=design_tokens, video_path=video_path
            )
        else:
            # 通常の単一生成
            return await self.image_generator.generate_from_image(
                image_path,
                html_content=html_content,
                video_path=video_path,
                design_tokens=design_tokens
            )

    async def _generate_multi_section(
        self,
        multi_gen: MultiSectionGenerator,
        image_path: str,
        job_id: str,
        html_content: str = None,
        design_tokens: dict = None,
        video_path: str = None
    ) -> dict:
        """マルチセクション生成（ステータス更新付き）

        フルページ（縦長画像）の場合は必ず分割生成を行う。
        3段階フローは通常サイズのページにのみ適用。
        """
        import time
        from app.config import settings
        from app.services.replicator.base_image_generator import ImageGenerationError
        
        # フルページは常に分割生成（3段階フローはバイパスしない）
        logger.info("Full page detected - using multi-section generation with splitting")
        from PIL import Image

        # 画像を読み込み
        img = Image.open(image_path)
        logger.info(f"Full page image size: {img.size}")

        # RGB変換
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # セクションに分割
        sections = multi_gen._split_image(img)
        logger.info(f"Split into {len(sections)} sections")

        # HTMLコンテンツがある場合、参照用情報を準備
        html_reference = ""
        if html_content:
            # HTMLが長すぎる場合は切り詰める（各セクションで使えるよう適切なサイズに）
            max_html_chars = 8000
            if len(html_content) > max_html_chars:
                html_reference = html_content[:max_html_chars] + "\n... (truncated)"
            else:
                html_reference = html_content
            logger.info(f"HTML reference content available: {len(html_reference)} chars")

        # デザイン要素の文字列化
        if design_tokens:
            design_colors = ", ".join(design_tokens.get("colors", []))
            design_fonts = ", ".join(design_tokens.get("fonts", []))
        else:
            design_colors = "(画像から推測)"
            design_fonts = "(画像から推測)"

        # 各セクションを生成
        results = []
        failed_sections = []
        section_metadata = []

        for i, section_img in enumerate(sections):
            section_number = i + 1
            start_time = time.time()

            try:
                logger.info(f"Generating section {section_number}/{len(sections)}...")

                # プロンプト作成
                if i == 0:
                    from app.services.replicator.multi_section_generator import SECTION_PROMPT_FIRST
                    prompt = SECTION_PROMPT_FIRST.format(
                        viewport_width=1366,
                        design_colors=design_colors,
                        design_fonts=design_fonts
                    )
                elif i == len(sections) - 1:
                    from app.services.replicator.multi_section_generator import SECTION_PROMPT_LAST
                    prompt = SECTION_PROMPT_LAST.format(
                        image_start_num=i*10+1,
                        design_colors=design_colors
                    )
                else:
                    from app.services.replicator.multi_section_generator import SECTION_PROMPT_MIDDLE
                    prompt = SECTION_PROMPT_MIDDLE.format(
                        section_num=i+1,
                        image_start_num=i*10+1,
                        design_colors=design_colors,
                        design_fonts=design_fonts
                    )

                # HTMLコンテンツがあればプロンプトに追加
                if html_reference:
                    prompt += f"""

## 参照用HTMLソース
以下は元のWebページのHTMLソースです。テキスト内容、構造、クラス名などを参考にしてください。
ただし、見た目の再現が最優先です。HTMLソースはあくまで参考情報として使用してください。

```html
{html_reference}
```
"""

                # セクション生成（リトライ機能付き）
                result = await multi_gen._generate_section(
                    section_img,
                    prompt,
                    section_number=section_number,
                    max_retries=settings.MAX_RETRIES,
                    retry_delay_base=settings.RETRY_BACKOFF_BASE
                )
                results.append(result)

                elapsed = time.time() - start_time
                html_len = len(result.get('html', ''))
                css_len = len(result.get('css', ''))
                js_len = len(result.get('js', ''))

                logger.info(
                    f"Section {section_number} generated successfully: "
                    f"HTML={html_len} chars, CSS={css_len} chars, JS={js_len} chars, "
                    f"time={elapsed:.2f}s"
                )

                section_metadata.append({
                    'section': section_number,
                    'status': 'success',
                    'time': elapsed,
                    'html_length': html_len
                })

                # レート制限対策: セクション間の遅延
                if i < len(sections) - 1:
                    await asyncio.sleep(1.5)

            except ImageGenerationError as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"Failed to generate section {section_number} after all retries: {e}",
                    exc_info=True
                )
                failed_sections.append(section_number)

                section_metadata.append({
                    'section': section_number,
                    'status': 'failed',
                    'time': elapsed,
                    'error': str(e)
                })

                # 最初のセクション（HTMLヘッダー）が失敗した場合は致命的
                if i == 0:
                    logger.error("First section (HTML header) failed - cannot continue")
                    raise ImageGenerationError(
                        f"Critical: First section failed to generate. Cannot create valid HTML document."
                    )

                # 最後のセクション（HTMLフッター）が失敗した場合も問題
                if i == len(sections) - 1:
                    logger.warning("Last section (HTML footer) failed - will attempt to close HTML manually")
                    # 最小限のフッターを生成
                    results.append({
                        'html': '</body>\n</html>',
                        'css': '/* Footer section failed */',
                        'js': '// Footer section failed'
                    })
                else:
                    # 中間セクションの失敗はプレースホルダーで対応
                    results.append({
                        'html': f'<!-- Section {section_number} generation failed: {str(e)} -->\n'
                               f'<section class="section-{section_number}-failed">\n'
                               f'  <div class="error-placeholder">\n'
                               f'    <p>このセクションの生成に失敗しました</p>\n'
                               f'  </div>\n'
                               f'</section>',
                        'css': f'/* Section {section_number} failed */\n'
                              f'.section-{section_number}-failed {{\n'
                              f'  padding: 2rem;\n'
                              f'  background: #f0f0f0;\n'
                              f'  text-align: center;\n'
                              f'}}\n',
                        'js': f'// Section {section_number} failed'
                    })

            except Exception as e:
                # 予期しないエラー
                elapsed = time.time() - start_time
                logger.exception(f"Unexpected error in section {section_number}: {e}")
                failed_sections.append(section_number)

                section_metadata.append({
                    'section': section_number,
                    'status': 'error',
                    'time': elapsed,
                    'error': str(e)
                })

                # 最初のセクション失敗は致命的
                if i == 0:
                    raise ImageGenerationError(f"Critical: First section failed unexpectedly: {e}")

                # その他は続行を試みる
                results.append({
                    'html': f'<!-- Section {section_number} error: {str(e)[:100]} -->',
                    'css': f'/* Section {section_number} error */',
                    'js': f'// Section {section_number} error'
                })

        # 結果の評価
        logger.info(f"Section generation completed: {len(results)} sections, {len(failed_sections)} failed")
        logger.info(f"Metadata: {section_metadata}")

        if not results:
            raise ImageGenerationError("All sections failed to generate")

        if len(failed_sections) == len(sections):
            raise ImageGenerationError("All sections failed to generate")

        # 部分的失敗の場合は警告
        if failed_sections:
            logger.warning(f"Partial generation: Failed sections = {failed_sections}")

        # 結合
        merged = multi_gen._merge_results(results)

        # メタデータをログに記録
        merged['_metadata'] = {
            'total_sections': len(sections),
            'successful_sections': len(sections) - len(failed_sections),
            'failed_sections': failed_sections,
            'section_details': section_metadata
        }

        return merged

    async def _save_files(self, job_id: str, code: dict) -> str:
        """
        生成ファイルを保存

        Returns:
            出力ディレクトリパス
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            output_dir_name = job.output_dir

        # 出力ディレクトリ作成
        output_dir = os.path.abspath(output_dir_name)
        os.makedirs(output_dir, exist_ok=True)

        # ファイル保存
        html_path = os.path.join(output_dir, "index.html")
        css_path = os.path.join(output_dir, "styles.css")
        js_path = os.path.join(output_dir, "script.js")

        # HTMLにCSS/JSリンクを追加（必要に応じて）
        html_content = code.get("html", "")

        # パスを正規化（./styles.css → styles.css）
        html_content = html_content.replace('href="./styles.css"', 'href="styles.css"')
        html_content = html_content.replace("href='./styles.css'", "href='styles.css'")
        html_content = html_content.replace('src="./script.js"', 'src="script.js"')
        html_content = html_content.replace("src='./script.js'", "src='script.js'")

        # style.css → styles.css に統一（AIが時々 style.css を生成するため）
        html_content = html_content.replace('href="style.css"', 'href="styles.css"')
        html_content = html_content.replace("href='style.css'", "href='styles.css'")

        # styles.cssへのリンクが存在しない場合のみ追加
        has_css_link = 'href="styles.css"' in html_content or "href='styles.css'" in html_content
        if not has_css_link and code.get("css"):
            # headタグ内にCSSリンクを追加
            if '</head>' in html_content:
                html_content = html_content.replace(
                    "</head>",
                    '  <link rel="stylesheet" href="styles.css">\n</head>'
                )
            elif '</HEAD>' in html_content:
                html_content = html_content.replace(
                    "</HEAD>",
                    '  <link rel="stylesheet" href="styles.css">\n</HEAD>'
                )

        # script.jsへのリンクが存在しない場合のみ追加
        has_js_link = 'src="script.js"' in html_content or "src='script.js'" in html_content
        if not has_js_link and code.get("js"):
            # bodyタグ終了前にJSを追加
            if '</body>' in html_content:
                html_content = html_content.replace(
                    "</body>",
                    '  <script src="script.js"></script>\n</body>'
                )
            elif '</BODY>' in html_content:
                html_content = html_content.replace(
                    "</BODY>",
                    '  <script src="script.js"></script>\n</BODY>'
                )

        # デバッグログ: code dictの内容を確認
        logger.info(f"Saving files - code dict keys: {list(code.keys())}")
        logger.info(f"HTML length: {len(html_content)}, CSS length: {len(code.get('css', ''))}, JS length: {len(code.get('js', ''))}")

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(code.get("css", ""))

        with open(js_path, 'w', encoding='utf-8') as f:
            f.write(code.get("js", ""))

        # DB更新
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            job.html_filename = "index.html"
            job.css_filename = "styles.css"
            job.js_filename = "script.js"
            await session.commit()

        logger.info(f"Files saved to: {output_dir}")
        return output_dir

    async def _update_status(
        self,
        job_id: str,
        status: ReplicationStatus,
        error_message: Optional[str] = None,
        warnings: Optional[str] = None
    ):
        """ステータス更新"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            job.status = status
            job.updated_at = datetime.utcnow()
            if error_message:
                job.error_message = error_message
            if warnings:
                job.warnings = warnings
            if status.value.startswith("verifying_"):
                job.current_iteration = int(status.value.split("_")[1])
            await session.commit()

        logger.info(f"Job {job_id} status: {status.value}")

    async def _analyze_screenshot_structure(
        self,
        image_path: str,
        image_data: str,
        image_type: str
    ) -> Optional[str]:
        """
        スクリーンショット画像を詳細に分析し、構造・デザイン情報を抽出
        （Claudeデスクトップアプリのscroll+screenshot+read_pageを模倣）

        Args:
            image_path: 画像パス
            image_data: Base64エンコード済み画像データ
            image_type: 画像タイプ（png/jpeg）

        Returns:
            分析結果テキスト（セクション構成、色、レイアウト、テキスト内容）
        """
        logger.info("=== Phase 1: Screenshot Structure Analysis ===")

        analysis_prompt = """この画像を、Webページの複製のために詳細に分析してください。

## 分析タスク

### 1. ページ構造の把握
- 上から順に、どのようなセクションがあるか列挙
- 各セクションの役割（ヘッダー、ヒーロー、商品詳細、フッターなど）

### 2. レイアウト分析
- 各セクションのレイアウト方式（フレックス、グリッド、固定配置）
- 要素の配置（中央揃え、左揃え、カラム数）
- 余白・パディング（大まかなサイズ感）

### 3. 色・スタイル分析
- 背景色（グラデーションの有無、色コード推定）
- テキスト色
- アクセントカラー
- フォントスタイル（太字、イタリック、サイズ感）

### 4. 視覚的要素
- 画像の位置・サイズ
- ボタン・バッジのスタイル
- シャドウ・ボーダーの有無
- アニメーション効果（もしあれば）

### 5. テキスト内容の抽出
- 主要な見出し
- 価格・型番などの具体的データ
- キャッチコピー

## 出力形式
箇条書きで、上から順にセクションごとに分析結果を記述してください。
"""

        try:
            response = self.image_generator.client.messages.create(
                model=self.image_generator.model,
                max_tokens=8000,  # 分析結果のみなので控えめ
                temperature=0.2,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": f"image/{image_type}",
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": analysis_prompt
                            }
                        ],
                    }
                ],
            )

            analysis_result = response.content[0].text
            logger.info(f"Screenshot analysis completed: {len(analysis_result)} chars")
            return analysis_result

        except Exception as e:
            logger.error(f"Screenshot analysis failed: {e}")
            return None

    async def _refine_generated_code(
        self,
        job_id: str,
        original_image_path: str,
        generated_code: dict,
        output_dir: str,
        source_url: Optional[str] = None
    ) -> Optional[dict]:
        """
        生成されたコードを元の画像と比較して改善（URL統合版）
        Phase 1: 画像の詳細分析
        Phase 2: 分析結果 + URL情報 + 既存コード全量での差分修正

        Args:
            job_id: ジョブID
            original_image_path: 元のスクリーンショット画像パス
            generated_code: 生成されたHTML/CSS/JS
            output_dir: 出力ディレクトリ
            source_url: 元のWebページURL（オプション）

        Returns:
            改善されたコード（dict）またはNone
        """
        import base64
        from PIL import Image
        import json
        import re

        logger.info("=== Refinement Step: 2-Phase Analysis & Matching ===")

        # 元の画像を読み込んでリサイズ（必要な場合）してBase64エンコード
        try:
            img = Image.open(original_image_path)
            image_type = img.format.lower() if img.format else 'png'

            # Claude APIの制限: 最大8000ピクセル
            max_dimension = 8000
            width, height = img.size

            if width > max_dimension or height > max_dimension:
                # アスペクト比を保持してリサイズ
                ratio = min(max_dimension / width, max_dimension / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                logger.info(f"Resizing image from {width}x{height} to {new_width}x{new_height}")
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Base64エンコード
            import io
            buffer = io.BytesIO()
            img.save(buffer, format=image_type.upper())
            image_data = base64.standard_b64encode(buffer.getvalue()).decode('utf-8')
            img.close()
        except Exception as e:
            logger.error(f"Failed to read original image: {e}")
            return None

        # Phase 1: 画像の詳細分析
        screenshot_analysis = await self._analyze_screenshot_structure(
            original_image_path,
            image_data,
            image_type
        )

        if not screenshot_analysis:
            logger.warning("Screenshot analysis failed, falling back to simple refinement")
            screenshot_analysis = "（画像分析に失敗したため、画像を直接参照してください）"

        # Phase 2: 分析結果 + 既存コード全量でリファインメント
        refinement_prompt = f"""# タスク: 画像ベースのコード改善（完全一致を目指す）


## Phase 1: 画像分析結果

以下は、参照画像（Webページのスクリーンショット）を詳細に分析した結果です：

{screenshot_analysis}

---

## Phase 2: 既存コードとの差分修正

添付画像は、上記分析の元となったスクリーンショット（正解デザイン）です。
以下の既存コードと、上記の画像分析結果を比較し、差分があれば修正してください。

## ⚠️ 最重要制約（厳守）

1. **コンテンツ量を絶対に減らさない**
   - HTMLの要素数、テキスト量は現状維持
   - セクションの削除・省略は禁止
   - 「...省略...」などのコメントで置き換えない

2. **構造変更は最小限**
   - クラス名、ID、タグ構造は極力保持
   - セマンティック構造（header, main, section等）は維持

3. **差分修正の優先順位**
   - 1位: CSS（色、余白、フォント、レイアウト）← ここに集中
   - 2位: HTML（属性、クラス名の微調整）
   - 3位: JS（原則変更不要）

4. **完全一致への調整ポイント**
   - 色（背景色、文字色、ボーダー色）を正確に
   - 余白・パディング（margin, padding）をピクセル単位で
   - フォント（サイズ、太さ、行間、font-family）を厳密に
   - レイアウト（配置、幅、高さ）を精密に
   - 影・グラデーション・視覚効果を忠実に再現

---

## 現在のコード（全量）

### HTML
```html
{generated_code.get('html', '')}
```

### CSS
```css
{generated_code.get('css', '')}
```

### JavaScript
```javascript
{generated_code.get('js', '')}
```

## 分析・調整手順
1. 画像を注意深く観察し、現在のコードとの視覚的差分を特定
2. 以下の点を中心に調整:
   - 色（背景色、文字色、ボーダー色）
   - 余白・パディング（margin, padding）
   - フォント（サイズ、太さ、行間、font-family）
   - レイアウト（配置、幅、高さ、flexbox/grid設定）
   - 影・グラデーション・視覚効果
3. 構造的な問題がある場合のみ、最小限のHTML調整を行う

## 出力形式（JSON、厳守）
```json
{{
  "html": "元のHTMLをほぼそのまま、必要最小限の調整のみ",
  "css": "画像に合わせて微調整されたCSS",
  "js": "元のJavaScriptをそのまま"
}}
```

## 注意事項
- コンテンツ量・要素数を減らさない
- 不要な要素を削除しない
- セクション全体を省略しない
- 完全一致を目指すが、コンテンツ削減はしない
- 元のコード量を下回らないように
- 画像との差分が小さい場合は、CSSのみ軽微な調整でOK
"""

        # Phase 2: Claude APIで改善
        try:
            response = self.image_generator.client.messages.create(
                model=self.image_generator.model,
                max_tokens=50000,  # 既存コード全量 + 余裕
                temperature=0.05,  # 極めて保守的（コンテンツ削減を最小化）
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": f"image/{image_type}",
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": refinement_prompt
                            }
                        ],
                    }
                ],
            )

            # レスポンスからJSONを抽出
            response_text = response.content[0].text

            # JSONブロックを抽出
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if not json_match:
                json_match = re.search(r'(\{.*?\})', response_text, re.DOTALL)

            if json_match:
                refined_code = json.loads(json_match.group(1))

                # コード量チェック
                original_total = len(generated_code.get('html', '')) + len(generated_code.get('css', '')) + len(generated_code.get('js', ''))
                refined_total = len(refined_code.get('html', '')) + len(refined_code.get('css', '')) + len(refined_code.get('js', ''))
                retention_rate = (refined_total / original_total * 100) if original_total > 0 else 0

                logger.info(f"Refinement - HTML: {len(refined_code.get('html', ''))} chars, CSS: {len(refined_code.get('css', ''))} chars, JS: {len(refined_code.get('js', ''))} chars")
                logger.info(f"Content retention rate: {retention_rate:.1f}%")

                # 80%未満に削減された場合は元のコードを使用
                if retention_rate < 80:
                    logger.warning(f"Content significantly reduced ({retention_rate:.1f}%). Using original code instead.")
                    return None

                # 90%未満の場合は警告のみ
                if retention_rate < 90:
                    logger.warning(f"Content retention rate is low ({retention_rate:.1f}%). Consider reviewing the refinement.")

                return refined_code
            else:
                logger.warning("Could not extract JSON from refinement response")
                return None

        except Exception as e:
            logger.error(f"Refinement API call failed: {e}")
            return None

    async def post_generation_url_refinement(self, job_id: str) -> bool:
        """
        生成完了後の追加リファインメントステップ（URL情報を使用）

        ユーザーの手動フロー：
        1. サイト複製で3ファイル生成
        2. 生成完了画面で「ブラッシュアップ」ボタンを押す
        3. URL情報を使ってデザインを完全一致させる

        Args:
            job_id: ジョブID

        Returns:
            True if refinement succeeded, False otherwise
        """
        # ジョブ情報取得
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            output_dir = job.output_dir
            input_folder = job.input_folder

        # URL情報を読み込み
        source_url = None
        try:
            # スクリーンショットファイルからベース名を取得
            screenshot_path = await self._find_screenshot(job_id)
            source_url = await self._read_url_file(job_id, screenshot_path)
        except Exception as e:
            logger.warning(f"Failed to read URL info: {e}")

        if not source_url:
            logger.info("No source URL available, skipping post-generation refinement")
            return False
            
        logger.info(f"Starting post-generation URL refinement: {source_url}")
        
        try:
            # 生成されたファイルを読み込む
            html_file = os.path.join(output_dir, "index.html")
            css_file = os.path.join(output_dir, "styles.css")
            js_file = os.path.join(output_dir, "script.js")
            
            with open(html_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
            with open(css_file, 'r', encoding='utf-8') as f:
                css_content = f.read()
            with open(js_file, 'r', encoding='utf-8') as f:
                js_content = f.read()
                
            # URL情報を使った追加リファインメントプロンプト
            post_refinement_prompt = f"""# タスク: 生成されたWebサイトを元のURLのデザインに完全一致させる

## 元のWebページ情報

**参考URL**: {source_url}

上記URLのWebページをキャプチャして生成したHTML/CSS/JSファイルです。
このURLのWebページのデザインに**完全一致**するように、以下の3ファイルを修正してください。

## 最重要目標

元のWebページ（{source_url}）のデザインと**ピクセル単位で完全一致**させることです。

特に以下の点に注意：
1. **色の完全一致**: 背景色、文字色、ボーダー色、グラデーション
2. **レイアウトの完全一致**: 余白、パディング、配置、サイズ
3. **フォントの完全一致**: font-family, font-size, font-weight, line-height, letter-spacing
4. **視覚効果の完全一致**: shadow, border-radius, opacity, transition

## 既存コード

### HTML (index.html)
```html
{html_content}
```

### CSS (styles.css)
```css
{css_content}
```

### JavaScript (script.js)
```javascript
{js_content}
```

## 出力形式

完全一致させた3ファイルを以下の形式で出力してください：

```html:index.html
[修正されたHTML全体]
```

```css:styles.css
[修正されたCSS全体]
```

```javascript:script.js
[修正されたJavaScript全体]
```

**重要**: コード全体を出力してください。省略せず、すべての行を含めてください。
"""

            # Anthropic APIを直接使用して追加リファインメント
            from anthropic import AsyncAnthropic
            import httpx

            # 長時間実行用のタイムアウト設定
            timeout = httpx.Timeout(600.0, connect=60.0)  # 10分タイムアウト
            client = AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY,
                timeout=timeout
            )

            response = await client.messages.create(
                model="claude-opus-4-20250514",
                max_tokens=16000,
                messages=[{
                    "role": "user",
                    "content": post_refinement_prompt
                }]
            )

            # レスポンスからコードを抽出
            refined_result = self._extract_code_blocks(response.content[0].text)

            # 抽出結果のログ
            logger.info(f"Extracted code lengths - HTML: {len(refined_result.get('html', ''))}, CSS: {len(refined_result.get('css', ''))}, JS: {len(refined_result.get('js', ''))}")

            # キーが存在し、かつ値が空でないことを確認
            has_valid_content = (
                refined_result.get('html') and
                refined_result.get('css') and
                len(refined_result['html']) > 100 and
                len(refined_result['css']) > 100
            )

            if has_valid_content:
                # リファインメント成功 - ファイルを上書き
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(refined_result['html'])
                with open(css_file, 'w', encoding='utf-8') as f:
                    f.write(refined_result['css'])
                with open(js_file, 'w', encoding='utf-8') as f:
                    f.write(refined_result.get('js', ''))

                logger.info(f"Post-generation URL refinement completed successfully")
                return True
            else:
                logger.warning(f"Post-generation refinement returned incomplete result - not overwriting files")
                logger.warning(f"Response preview: {response.content[0].text[:500]}...")
                return False
                
        except Exception as e:
            logger.error(f"Post-generation URL refinement failed: {e}")
            return False


    def _extract_code_blocks(self, text: str) -> dict:
        """
        Claude APIレスポンスからコードブロックを抽出
        
        Args:
            text: Claude APIのレスポンステキスト
            
        Returns:
            {'html': str, 'css': str, 'js': str}
        """
        import re
        
        result = {'html': '', 'css': '', 'js': ''}
        
        # HTML抽出
        html_match = re.search(r'```html:index\.html\s*\n(.*?)```', text, re.DOTALL)
        if not html_match:
            html_match = re.search(r'```html\s*\n(.*?)```', text, re.DOTALL)
        if html_match:
            result['html'] = html_match.group(1).strip()
            
        # CSS抽出
        css_match = re.search(r'```css:styles\.css\s*\n(.*?)```', text, re.DOTALL)
        if not css_match:
            css_match = re.search(r'```css\s*\n(.*?)```', text, re.DOTALL)
        if css_match:
            result['css'] = css_match.group(1).strip()
            
        # JavaScript抽出  
        js_match = re.search(r'```javascript:script\.js\s*\n(.*?)```', text, re.DOTALL)
        if not js_match:
            js_match = re.search(r'```javascript\s*\n(.*?)```', text, re.DOTALL)
        if not js_match:
            js_match = re.search(r'```js\s*\n(.*?)```', text, re.DOTALL)
        if js_match:
            result['js'] = js_match.group(1).strip()
            
        return result

