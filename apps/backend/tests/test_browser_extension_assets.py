import json
import unittest
from pathlib import Path


class BrowserExtensionAssetsTestCase(unittest.TestCase):
    def test_manifest_references_required_files(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        extension_root = project_root / 'browser-extension'

        manifest = json.loads((extension_root / 'manifest.json').read_text(encoding='utf-8'))

        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['background']['service_worker'], 'background.js')
        self.assertEqual(manifest['action']['default_title'], '飞猪运营助手')
        self.assertEqual(manifest['options_page'], 'options.html')
        self.assertIn('tabs', manifest['permissions'])

        content_scripts = manifest['content_scripts']
        self.assertTrue(content_scripts)
        self.assertEqual(
            content_scripts[0]['js'],
            [
                'content/page-context.js',
                'content/result-view.js',
                'content.js',
            ],
        )

        for file_name in [
            'background.js',
            'content.js',
            'popup.html',
            'popup.js',
            'options.html',
            'options.js',
            'README.md',
            'content/page-context.js',
            'content/result-view.js',
        ]:
            self.assertTrue((extension_root / file_name).exists(), file_name)

    def test_extension_contains_workflow_first_popup(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        extension_root = project_root / 'browser-extension'
        content_js = (extension_root / 'content.js').read_text(encoding='utf-8')
        popup_html = (extension_root / 'popup.html').read_text(encoding='utf-8')
        popup_js = (extension_root / 'popup.js').read_text(encoding='utf-8')
        background_js = (extension_root / 'background.js').read_text(encoding='utf-8')
        options_html = (extension_root / 'options.html').read_text(encoding='utf-8')
        options_js = (extension_root / 'options.js').read_text(encoding='utf-8')
        page_context_js = (extension_root / 'content/page-context.js').read_text(encoding='utf-8')

        self.assertIn('GET_PAGE_CONTEXT', content_js)
        self.assertIn('OPEN_PANEL', content_js)
        self.assertIn('data-action="room-prices"', content_js)
        self.assertIn('data-action="auth-login"', content_js)
        self.assertIn('data-action="auth-logout"', content_js)
        self.assertIn('当前未登录，请先登录插件账号并选择店铺。', content_js)
        self.assertIn('data-action="refresh-room-config"', content_js)
        self.assertIn('data-action="merchant-pricing-load"', content_js)
        self.assertIn('data-action="merchant-uniform-submit"', content_js)
        self.assertIn('merchantPlatformLinks', content_js)
        self.assertIn('merchantPlatformLinks', background_js)
        self.assertIn('这里恢复为单链接模式，直接使用已保存的商家价格页链接。', content_js)
        self.assertIn('商家价格页 URL', content_js)
        self.assertIn('商家价格页链接: ', content_js)
        self.assertNotIn('data-action="merchant-pricing-preview"', content_js)
        self.assertNotIn('data-action="merchant-pricing-fill"', content_js)
        self.assertNotIn('data-action="merchant-pricing-submit"', content_js)
        self.assertIn('COMPETITOR_ROOM_PRICE_MESSAGE_TYPES', content_js)
        self.assertIn('requestViaExtensionBridge("competitor-room-prices", payload)', content_js)
        self.assertIn('/plugin/competitor/room-prices', content_js)
        self.assertIn('COMPETITOR_ROOM_PRICES', content_js)
        self.assertIn('fetchCompetitorRoomPricesDirect', content_js)
        self.assertIn('renderConfiguredCompetitorHotelsSummary', content_js)
        self.assertIn('竞对驱动改价', popup_html)
        self.assertIn('目标价直改', popup_html)
        self.assertIn('配置竞对房型价', popup_html)
        self.assertIn('竞对建议价', popup_html)
        self.assertIn('抓取配置房型价', popup_html)
        self.assertIn('生成建议价', popup_html)
        self.assertIn('账号登录', popup_html)
        self.assertIn('登录并进入', popup_html)
        self.assertIn('当前店铺', popup_html)
        self.assertIn('快捷动作', popup_html)
        self.assertIn('开始分析', popup_html)
        self.assertIn('一键确认改价', popup_html)
        self.assertIn('按当前页采集', popup_html)
        self.assertNotIn('读取竞对价格', popup_html)
        self.assertIn('chrome.tabs.query', popup_js)
        self.assertIn('type: "RUN_COLLECT"', popup_js)
        self.assertIn('type: "COMPETITOR_WORKFLOW_PREVIEW"', popup_js)
        self.assertIn('type: "COMPETITOR_PRICING_ADVICE_PREVIEW"', popup_js)
        self.assertIn('type: "MERCHANT_PRICING_SUBMIT_CURRENT"', popup_js)
        self.assertIn('type: "MERCHANT_UNIFORM_PRICE_SUBMIT"', popup_js)
        self.assertIn('MERCHANT_PRICING_ITEMS', background_js)
        self.assertIn('type: "AUTH_LOGIN"', popup_js)
        self.assertIn('type: "AUTH_SWITCH_SHOP"', popup_js)
        self.assertIn('COMPETITOR_ROOM_PRICE_MESSAGE_TYPES', popup_js)
        self.assertIn('requestCompetitorRoomPrices(payload)', popup_js)
        self.assertIn('normalizeWorkflowPreview', popup_js)
        self.assertIn('renderConfiguredCompetitorHotels', popup_js)
        self.assertIn('renderCompetitorRoomPrices', popup_js)
        self.assertIn('renderCompetitorPricingAdvice', popup_js)
        self.assertIn('collectConfirmedWorkflowItems', popup_js)
        self.assertIn('renderWorkflowPreview', popup_js)
        self.assertIn('previewCompetitorWorkflow', background_js)
        self.assertIn('previewCompetitorPricingAdvice', background_js)
        self.assertIn('submitUniformMerchantPricing', background_js)
        self.assertIn('COMPETITOR_WORKFLOW_PREVIEW', background_js)
        self.assertIn('COMPETITOR_PRICING_ADVICE_PREVIEW', background_js)
        self.assertIn('MERCHANT_UNIFORM_PRICE_SUBMIT', background_js)
        self.assertIn('COMPETITOR_ROOM_PRICES', background_js)
        self.assertIn('competitorHotels', background_js)
        self.assertIn('normalizeCompetitorHotels', background_js)
        self.assertIn('crawlCompetitorRoomPricesViaTabs', background_js)
        self.assertIn('/plugin/auth/login', background_js)
        self.assertIn('/plugin/competitor/hotels', background_js)
        self.assertIn('/plugin/pricing/competitor-workflow-preview', background_js)
        self.assertIn('/plugin/pricing/competitor-advice-preview', background_js)
        self.assertIn('/plugin/pricing/uniform-direct-submit', background_js)
        self.assertIn('price_signals', background_js)
        self.assertNotIn('OPEN_PROJECT_PAGE', popup_js)
        self.assertNotIn('OPEN_PROJECT_PAGE', content_js)
        self.assertNotIn('PROJECT_PAGES', background_js)
        self.assertIn('竞对酒店配置', options_html)
        self.assertIn('auth-summary', options_html)
        self.assertIn('competitorHotels', options_js)
        self.assertIn('readCompetitorHotels', options_js)
        self.assertIn('ensureAuthenticated', options_js)
        self.assertIn('extractPriceSignals', page_context_js)
        self.assertIn('pickBestPrice', page_context_js)
        self.assertIn('price_text', page_context_js)
        self.assertIn('collectTargetHintCandidateNodes', page_context_js)
        self.assertIn('resolveCandidateContainerFromHint', page_context_js)
        self.assertIn('collectAllPages: false', popup_js)
        self.assertIn('targetHotelNames: manualTargets', popup_js)
        self.assertIn('collectAllPages: false', content_js)
        self.assertIn('targetHotelNames: manualTargets', content_js)
        self.assertNotIn('data-action="prices"', content_js)


if __name__ == '__main__':
    unittest.main()




