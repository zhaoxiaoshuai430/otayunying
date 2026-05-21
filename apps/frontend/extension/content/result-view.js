(() => {
  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;")
  }

  function renderPageContext(node, pageContext) {
    const tags = pageContext.targetHotelNames.length
      ? `<div class="fliggy-ops-tags">${pageContext.targetHotelNames.map((name) => `<span class="fliggy-ops-tag">${escapeHtml(name)}</span>`).join("")}</div>`
      : '<div class="fliggy-ops-footer">当前页未识别到明确酒店名，将只使用当前 URL 作为采集入口。</div>'

    const pageTips = []
    if (pageContext.pageType === "login_redirect") {
      pageTips.push("当前页是登录跳转页，采集会优先使用跳转后的目标 URL。")
    }
    if (pageContext.pageType === "merchant_portal") {
      pageTips.push("当前页属于商家后台，优先使用商家改价、会话维护和页面内操作，不建议把这里当作酒店列表采集页。")
    }
    if (pageContext.hostname.includes("error.taobao.com")) {
      pageTips.push("当前页落在错误页，建议先回到酒店列表或商家后台再执行采集。")
    }

    node.innerHTML = `
      <div class="fliggy-ops-meta">
        <div class="fliggy-ops-row"><span class="fliggy-ops-label">页面类型</span><span class="fliggy-ops-value">${escapeHtml(pageContext.pageType)}</span></div>
        <div class="fliggy-ops-row"><span class="fliggy-ops-label">城市</span><span class="fliggy-ops-value">${escapeHtml(pageContext.cityName || "-")}</span></div>
        <div class="fliggy-ops-row"><span class="fliggy-ops-label">日期</span><span class="fliggy-ops-value">${escapeHtml(pageContext.checkIn || "-")} -> ${escapeHtml(pageContext.checkOut || "-")}</span></div>
        <div class="fliggy-ops-row"><span class="fliggy-ops-label">关键词</span><span class="fliggy-ops-value">${escapeHtml(pageContext.keyword || "-")}</span></div>
      </div>
      ${tags}
      ${pageTips.length ? `<div class="fliggy-ops-footer">${pageTips.map(escapeHtml).join(" ")}</div>` : ""}
    `
  }

  function summarizeCollectContext(pageContext) {
    return {
      page_type: pageContext.pageType,
      city_name: pageContext.cityName,
      check_in: pageContext.checkIn,
      check_out: pageContext.checkOut,
      keyword: pageContext.keyword,
      target_hotel_names: pageContext.targetHotelNames,
      target_page_url_keyword: pageContext.targetPageUrlKeyword
    }
  }

  function renderLatestPrices(response, pageContext) {
    const items = (response.hotels || [])
      .map((hotel) => `<li><strong>${escapeHtml(hotel.hotel_name || hotel.name || "-")}</strong><br>价格: ${escapeHtml(String(hotel.price ?? hotel.min_price ?? "-"))}</li>`)
      .join("")

    const header = `当前页: ${pageContext.cityName || pageContext.keyword || pageContext.pageType} | 共 ${response.count ?? response.hotel_count ?? 0} 条 | 最近采集 ${response.latest_collected_at || response.collected_at || "-"}`
    if (!items) {
      return `${escapeHtml(header)}<div class="fliggy-ops-footer">暂无数据</div>`
    }
    return `${escapeHtml(header)}<ol class="fliggy-ops-list">${items}</ol>`
  }

  function normalizeName(value) {
    return String(value || "").replace(/\s+/g, "").toLowerCase()
  }

  function extractPrice(text) {
    const matched = String(text || "").replace(/,/g, "").match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/)
    if (matched) {
      return `¥${matched[1]}`
    }
    const fallback = String(text || "").replace(/,/g, "").match(/\b(\d{2,5}(?:\.\d{1,2})?)\b/)
    return fallback ? `¥${fallback[1]}` : "-"
  }

  function buildLocalCollectResult(pageSnapshot, targetHotelNames) {
    const rows = Array.isArray(pageSnapshot?.candidateRows) ? pageSnapshot.candidateRows : []
    const targets = Array.isArray(targetHotelNames) ? targetHotelNames.filter(Boolean) : []
    const normalizedTargets = targets.map((name) => ({ raw: name, key: normalizeName(name) }))
    const items = []
    const matched = new Set()
    const targetMatchItems = []

    for (const row of rows) {
      const rowName = String(row?.name || "").trim()
      const rowKey = normalizeName(rowName)
      const rowText = String(row?.text || "")
      const matchedTargets = normalizedTargets.filter((target) => target.key && rowKey && (rowKey.includes(target.key) || target.key.includes(rowKey)))
      const item = {
        name: rowName || "unknown",
        url: String(row?.href || pageSnapshot?.pageContext?.startUrl || ""),
        signals: {
          price_signals: [extractPrice(rowText)]
        }
      }
      matchedTargets.forEach((target) => {
        if (matched.has(target.raw)) {
          return
        }
        matched.add(target.raw)
        targetMatchItems.push({
          target_name: target.raw,
          matched_name: item.name,
          price: item.signals.price_signals[0] || "-",
          url: item.url
        })
      })
      items.push(item)
    }

    return {
      collect_mode: "extension_page_local",
      raw_row_count: rows.length,
      kept_row_count: items.length,
      filtered_row_count: Math.max(0, rows.length - items.length),
      count: items.length,
      items,
      matched_target_hotel_names: targets.filter((name) => matched.has(name)),
      missing_target_hotel_names: targets.filter((name) => !matched.has(name)),
      target_hotel_names: targets,
      target_match_items: targetMatchItems,
      filter_summary: {},
      filtered_examples: []
    }
  }

  function renderCollectSummary(response, pageContext) {
    const items = Array.isArray(response.items) ? response.items : []
    const filteredExamples = Array.isArray(response.filtered_examples) ? response.filtered_examples : []
    const filterSummary = response.filter_summary || {}
    const missingTargets = Array.isArray(response.missing_target_hotel_names) ? response.missing_target_hotel_names : []
    const matchedTargets = Array.isArray(response.matched_target_hotel_names) ? response.matched_target_hotel_names : []
    const targetMatchItems = Array.isArray(response.target_match_items) ? response.target_match_items : []
    const allHotelsHtml = items
      .map((hotel) => {
        const signals = hotel.signals || {}
        const prices = Array.isArray(signals.price_signals) ? signals.price_signals : []
        return `<li><strong>${escapeHtml(hotel.name || "-")}</strong><br>价格: ${escapeHtml(prices[0] || "-")}</li>`
      })
      .join("")
    const targetHotelHtml = targetMatchItems
      .map((hotel) => `<li><strong>${escapeHtml(hotel.target_name || hotel.matched_name || "-")}</strong><br>当前页命中: ${escapeHtml(hotel.matched_name || "-")}<br>价格: ${escapeHtml(String(hotel.price || "-"))}</li>`)
      .join("")


    const filteredExampleHtml = filteredExamples
      .slice()
      .sort((left, right) => {
        const leftReason = String(left?.reason || "")
        const rightReason = String(right?.reason || "")
        const leftScore = leftReason === "target_hotel_name_mismatch" ? 0 : 1
        const rightScore = rightReason === "target_hotel_name_mismatch" ? 0 : 1
        return leftScore - rightScore
      })
      .slice(0, 5)
      .map((example) => {
        const examplePrice = example?.price || "-"
        const exampleReason = example?.reason || "-"
        const exampleName = example?.name || "unknown"
        const exampleText = String(example?.raw_text || "").slice(0, 120)
        return `<li><strong>${escapeHtml(exampleName)}</strong><br>价格: ${escapeHtml(String(examplePrice))} | 原因: ${escapeHtml(exampleReason)}${exampleText ? `<br>片段: ${escapeHtml(exampleText)}` : ""}</li>`
      })
      .join("")
    const filterSummaryText = Object.keys(filterSummary).length
      ? Object.entries(filterSummary).map(([reason, count]) => `${reason}: ${count}`).join(" | ")
      : "无"

    return `
      <div class="fliggy-ops-footer">采集模式: ${escapeHtml(response.collect_mode || "unknown")} | 页面类型: ${escapeHtml(pageContext.pageType)} | 城市: ${escapeHtml(pageContext.cityName || "-")} | 手工目标: ${escapeHtml(String(pageContext.targetHotelNames.length))}</div>
      <div class="fliggy-ops-footer">Raw Rows: ${escapeHtml(String(response.raw_row_count ?? response.count ?? 0))} | Matched: ${escapeHtml(String(response.kept_row_count ?? response.count ?? 0))} | Filtered: ${escapeHtml(String(response.filtered_row_count ?? 0))}</div>
      ${response.warning_message ? `<div class="fliggy-ops-footer">提示: ${escapeHtml(response.warning_message)}</div>` : ""}
      ${matchedTargets.length ? `<div class="fliggy-ops-footer">命中酒店: ${escapeHtml(matchedTargets.join(" / "))}</div>` : ""}
      <div class="fliggy-ops-footer">过滤摘要: ${escapeHtml(filterSummaryText)}</div>
      ${response.saved_count !== undefined ? `<div class="fliggy-ops-footer">已保存: ${escapeHtml(String(response.saved_count))}</div>` : ""}
      ${missingTargets.length ? `<div class="fliggy-ops-footer">未命中: ${escapeHtml(missingTargets.join(" / "))}</div>` : ""}
      ${targetHotelHtml ? `<div class="fliggy-ops-footer">目标酒店价格</div><ol class="fliggy-ops-list">${targetHotelHtml}</ol>` : ""}
      ${allHotelsHtml ? `<div class="fliggy-ops-footer">当前页全部酒店价格</div><ol class="fliggy-ops-list">${allHotelsHtml}</ol>` : '<div class="fliggy-ops-footer">当前页未识别到酒店价格</div>'}
      ${filteredExamples.length ? `<div class="fliggy-ops-footer">过滤样例: ${escapeHtml(String(filteredExamples.length))} 条</div>` : ""}
      ${filteredExampleHtml ? `<ol class="fliggy-ops-list">${filteredExampleHtml}</ol>` : ""}
    `
  }

  window.FliggyOpsResultView = {
    escapeHtml,
    renderPageContext,
    summarizeCollectContext,
    renderLatestPrices,
    renderCollectSummary,
    buildLocalCollectResult
  }
})()

