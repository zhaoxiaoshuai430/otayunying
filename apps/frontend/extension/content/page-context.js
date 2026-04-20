(() => {
  const CANDIDATE_CONTAINER_SELECTORS = ["a[href*='hotel']", "a[href*='jiudian']", "[class*='hotel'][class*='item']", "[class*='hotel'][class*='card']", "[class*='list'] [class*='item']", "[class*='hotel']", "[class*='item']", "[class*='card']", "li", "article", "section", "div", "a"]
  const PRIMARY_HOTEL_LINK_SELECTORS = ["a[href*='hotel_detail']", "a[href*='/hotel/']", "a[href*='item.htm?id=']"]
  const FALLBACK_HOTEL_LINK_SELECTORS = ["a[href*='hotel.fliggy.com']", "a[href*='jiudian']"]
  const HOTEL_KEYWORDS = ["酒店", "宾馆", "民宿", "客栈", "公寓", "旅舍", "大酒店", "度假", "hotel", "resort", "inn", "hostel", "apartment", "suite"]
  const HOTEL_CONTEXT_KEYWORDS = ["评分", "点评", "评论", "预订", "入住", "离店", "双床", "大床", "含早", "无早", "每晚", "起订", "起", "可取消", "立即预订", "订房"]
  const NON_HOTEL_KEYWORDS = ["机票", "航班", "航线", "出发", "到达", "往返", "单程", "中转", "机场", "火车票", "门票"]
  const AGGREGATE_HOTEL_BLOCK_KEYWORDS = ["酒店推荐", "酒店信息", "住宿推荐", "国内酒店推荐", "为您提供", "精选了", "家酒店", "酒店预订", "特惠酒店", "尽在飞猪"]
  const SIDEBAR_HOTEL_BLOCK_KEYWORDS = ["我浏览过的酒店", "浏览过的酒店", "酒店侧边栏"]
  const SIDEBAR_HOTEL_CLASS_KEYWORDS = ["hotel-viewed", "hotel-side-box", "hotel-list-side", "hotel-list-sub"]
  const PRICE_POSITIVE_HINTS = ["每晚", "起", "预订", "到手", "含税", "未税", "现价", "促销价", "订", "住", "首晚", "连住", "低至", "仅需"]
  const PRICE_NEGATIVE_HINTS = ["原价", "门市价", "划线价", "参考价", "已减", "立减", "返现", "补贴", "优惠券", "券后", "红包", "返", "减"]
  const HOTEL_MARKETING_SUFFIX_PATTERNS = [/(:?[\s|｜/·•~_-]|[【\[\(（])*(?:会员价|限时抢购|今日特惠|今夜特惠|优惠价|专享价|抢购价|券后价|返现优惠|连住优惠|提前订优惠|早订优惠|新客专享|品牌特惠|门店特惠)[】\]\)）\s|｜/·•~_-]*$/i, /(?:[\s|｜/·•~_-]|[【\[\(（])*(?:立减|立省)\s*\d+(?:\.\d+)?\s*(?:元|起)?[】\]\)）\s|｜/·•~_-]*$/i, /(?:[\s|｜/·•~_-]|[【\[\(（])*(?:立减|立省)[】\]\)）\s|｜/·•~_-]*$/i]

  function detectPageContext() {
    const sourceUrl = new URL(window.location.href)
    const url = resolveSourceUrl(sourceUrl)
    const params = url.searchParams
    const targetHotelNames = collectCandidateHotelNames()
    const keyword = cleanText(params.get("keywords") || params.get("keyword") || detectKeywordFromInputs())
    const urlCityName = cleanText(params.get("cityName"))
    const cityName = cleanText(detectCityNameFromInputs() || detectCityNameFromTitle() || urlCityName)
    const checkIn = cleanText(params.get("checkIn") || detectDateLabel("入住") || detectDateLabel("入店"))
    const checkOut = cleanText(params.get("checkOut") || detectDateLabel("离店") || detectDateLabel("离开"))
    const targetPageUrlKeyword = inferTargetPageUrlKeyword(url)

    return {
      pageTitle: document.title,
      hostname: url.hostname,
      pathname: url.pathname,
      pageType: inferPageType(url, sourceUrl),
      sourcePageUrl: sourceUrl.toString(),
      startUrl: url.toString(),
      cityId: cleanText(params.get("city")),
      cityName,
      keyword,
      checkIn,
      checkOut,
      targetHotelNames,
      targetPageUrlKeyword,
      detectedAt: new Date().toLocaleString()
    }
  }

  function resolveSourceUrl(currentUrl) {
    const redirectKeys = ["redirectURL", "redirectUrl", "redirect", "ru"]
    for (const key of redirectKeys) {
      const rawValue = currentUrl.searchParams.get(key)
      if (!rawValue) {
        continue
      }
      try {
        return new URL(decodeURIComponent(rawValue), currentUrl.origin)
      } catch (error) {
        continue
      }
    }
    return currentUrl
  }

  function inferPageType(url, sourceUrl) {
    const full = `${url.hostname}${url.pathname}${url.search}`.toLowerCase()
    const source = sourceUrl.toString().toLowerCase()
    if (source.includes("login.taobao.com") && source.includes("redirecturl=")) {
      return "login_redirect"
    }
    if (full.includes("hotel_list")) {
      return "hotel_list"
    }
    if (full.includes("/hotel/") || full.includes("hotel_detail") || full.includes("hotel.htm")) {
      return "hotel_detail"
    }
    if (full.includes("ebooking") || full.includes("merchant")) {
      return "merchant_portal"
    }
    if (full.includes("/jiudian")) {
      return "hotel_home"
    }
    return "generic"
  }

  function inferTargetPageUrlKeyword(url) {
    const full = `${url.hostname}${url.pathname}`.toLowerCase()
    if (full.includes("hotel_list")) {
      return "hotel_list"
    }
    if (full.includes("/jiudian")) {
      return "jiudian"
    }
    return ""
  }

  function detectKeywordFromInputs() {
    return readInputValue([
      'input[placeholder*="关键词"]',
      'input[placeholder*="酒店"]',
      'input[name*="keyword"]',
      'input[type="search"]',
      '[contenteditable="true"]'
    ]) || readLabeledValue(["关键词", "酒店", "位置/品牌/酒店"]) || ""
  }

  function detectCityNameFromInputs() {
    return readInputValue([
      'input[placeholder*="目的地"]',
      'input[placeholder*="城市"]',
      'input[placeholder*="位置"]',
      'input[placeholder*="目的地/酒店"]'
    ]) || readLabeledValue(["目的地", "城市", "位置"]) || ""
  }

  function detectCityNameFromTitle() {
    const title = cleanText(document.title || "")
    const matched = title.match(/([\u4e00-\u9fff]{2,8})(?:酒店|住宿|宾馆|民宿|客栈)/)
    return matched ? cleanText(matched[1]) : ""
  }

  function detectDateLabel(keyword) {
    const labeled = readLabeledValue([keyword])
    if (labeled) {
      const matched = labeled.match(/(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})/)
      if (matched) {
        return matched[1]
      }
    }
    const text = document.body?.innerText || ""
    const index = text.indexOf(keyword)
    if (index === -1) {
      return ""
    }
    const snippet = text.slice(index, index + 60).replace(/\s+/g, " ").trim()
    const matched = snippet.match(/(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})/)
    return matched ? matched[1] : ""
  }

  function readInputValue(selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector)
      if (!element) {
        continue
      }
      const value = cleanText(element.value || element.textContent || element.getAttribute("value") || "")
      if (value) {
        return value
      }
    }
    return ""
  }

  function readLabeledValue(labels) {
    const elements = Array.from(document.querySelectorAll("label, span, div, strong, p"))
    for (const element of elements) {
      const text = cleanText(element.textContent || "")
      if (!text || !labels.some((label) => text === label || text.startsWith(`${label}:`) || text.startsWith(label))) {
        continue
      }
      const candidates = [
        element.nextElementSibling,
        element.parentElement?.nextElementSibling,
        element.parentElement?.querySelector("input, [contenteditable='true'], span, div")
      ].filter(Boolean)
      for (const candidate of candidates) {
        const value = cleanText(candidate.value || candidate.textContent || candidate.getAttribute?.("value") || "")
        if (value && value !== text) {
          return value
        }
      }
    }
    return ""
  }

  function collectCandidateHotelNames() {
    const elements = Array.from(document.querySelectorAll("a, h1, h2, h3, [title], [data-title], span, div"))
    const names = []
    const seen = new Set()
    for (const element of elements) {
      const raw = element.getAttribute("title") || element.dataset?.title || element.textContent || ""
      const href = element.href || element.closest?.("a")?.href || ""
      const className = typeof element.className === "string" ? element.className : ""
      const name = normalizeHotelName(raw || "", href, className)
      if (!name) {
        continue
      }
      const key = normalizeMatchText(name)
      if (!key || seen.has(key)) {
        continue
      }
      seen.add(key)
      names.push(name)
      if (names.length >= 8) {
        break
      }
    }
    return names
  }

  function collectTargetHintCandidateNodes(requestedTargets = []) {
    const targets = Array.isArray(requestedTargets) ? requestedTargets.filter(Boolean) : []
    if (!targets.length) {
      return []
    }

    const nodes = []
    const seenElements = new Set()
    const elements = Array.from(document.querySelectorAll("a, h1, h2, h3, h4, [title], [data-title], span, div")).slice(0, 1200)
    for (const element of elements) {
      if (!element) {
        continue
      }
      const rawText = cleanText(
        element.getAttribute?.("title") ||
        element.dataset?.title ||
        element.innerText ||
        element.textContent ||
        ""
      )
      const className = typeof element.className === "string" ? element.className : ""
      if (!rawText || looksLikeSidebarHotelBlock({ rawText, className }) || !targets.some((target) => targetMatchesKeyword(rawText, target))) {
        continue
      }
      const container = resolveCandidateContainerFromHint(element)
      if (!container || seenElements.has(container)) {
        continue
      }
      seenElements.add(container)
      nodes.push(container)
      if (nodes.length >= 40) {
        break
      }
    }
    return nodes
  }

  function collectPreferredCandidateNodes(requestedTargets = []) {
    const nodes = []
    const seenElements = new Set()

    for (const element of collectTargetHintCandidateNodes(requestedTargets)) {
      if (!element || seenElements.has(element)) {
        continue
      }
      seenElements.add(element)
      nodes.push(element)
    }

    for (const selector of PRIMARY_HOTEL_LINK_SELECTORS) {
      const links = Array.from(document.querySelectorAll(selector)).slice(0, 200)
      for (const link of links) {
        const container = resolveCandidateContainerFromLink(link)
        if (!container || seenElements.has(container)) {
          continue
        }
        seenElements.add(container)
        nodes.push(container)
      }
      if (nodes.length >= 120) {
        break
      }
    }

    if (nodes.length >= 6) {
      return nodes
    }

    for (const selector of FALLBACK_HOTEL_LINK_SELECTORS) {
      const links = Array.from(document.querySelectorAll(selector)).slice(0, 120)
      for (const link of links) {
        const container = resolveCandidateContainerFromLink(link)
        if (!container || seenElements.has(container)) {
          continue
        }
        seenElements.add(container)
        nodes.push(container)
      }
      if (nodes.length >= 80) {
        break
      }
    }

    if (nodes.length >= 6) {
      return nodes
    }

    for (const selector of CANDIDATE_CONTAINER_SELECTORS) {
      const matches = Array.from(document.querySelectorAll(selector)).slice(0, 160)
      for (const element of matches) {
        if (!element || seenElements.has(element)) {
          continue
        }
        seenElements.add(element)
        nodes.push(element)
      }
      if (nodes.length >= 220) {
        break
      }
    }

    return nodes
  }

  function resolveCandidateContainerFromLink(link) {
    if (!link) {
      return null
    }

    const linkHref = toAbsoluteUrl(link.getAttribute?.("href") || link.href || "")
    const linkClassName = typeof link.className === "string" ? link.className : ""
    const linkName = normalizeHotelName(
      link.getAttribute?.("title") || link.getAttribute?.("aria-label") || link.innerText || link.textContent || "",
      linkHref,
      linkClassName
    )

    let best = null
    let current = link
    for (let depth = 0; current && depth < 6; depth += 1) {
      const rawText = cleanText(String(current.innerText || current.textContent || ""))
      if (rawText && rawText.length >= 12 && rawText.length <= 720 && !looksLikeTransportText(rawText)) {
        const href = resolveHref(current) || linkHref
        const lines = splitLines(rawText)
        const className = typeof current.className === "string" ? current.className : ""
        if (looksLikeSidebarHotelBlock({ rawText, className })) {
          current = current.parentElement
          continue
        }
        const hotelLinkCount = countLikelyHotelLinks(current)
        if (!lines.length || lines.length > 18 || hotelLinkCount > 4) {
          current = current.parentElement
          continue
        }
        const nameNode = current.querySelector?.('h1,h2,h3,h4,[class*="title"],[class*="name"],[class*="hotel"]')
        const rawName = normalizeHotelName(linkName || nameNode?.innerText || detectHotelNameFromLines(lines, href, className) || lines[0] || "", href, className)
        const priceSignals = extractPriceSignals(lines)
        const score = scoreHotelCard({ rawName, rawText, href, className, lines, priceSignals, hotelLinkCount })
        const hasStrongNameSignal = isLikelyHotelName(rawName || linkName, href, className)
        if (!looksLikeAggregateHotelBlock({ rawName, rawText, lines, priceSignals }) && (hasStrongNameSignal || (priceSignals.length && score >= 5))) {
          const candidate = {
            element: current,
            score: score + (priceSignals.length ? 2 : 0) - depth - Math.max(0, hotelLinkCount - 2) - Math.max(0, lines.length - 8) - Math.floor(rawText.length / 220)
          }
          if (!best || candidate.score > best.score) {
            best = candidate
          }
        }
      }
      current = current.parentElement
    }

    return best?.element || null
  }

  function resolveCandidateContainerFromHint(element) {
    if (!element) {
      return null
    }

    const directLink = element.closest?.("a[href]") || (typeof element.matches === "function" && element.matches("a[href]") ? element : null)
    if (directLink) {
      const fromLink = resolveCandidateContainerFromLink(directLink)
      if (fromLink) {
        return fromLink
      }
    }

    let current = element
    for (let depth = 0; current && depth < 6; depth += 1) {
      const rawText = cleanText(String(current.innerText || current.textContent || ""))
      if (rawText && rawText.length >= 12 && rawText.length <= 900 && !looksLikeTransportText(rawText)) {
        const lines = splitLines(rawText)
        const href = resolveHref(current)
        const className = typeof current.className === "string" ? current.className : ""
        if (looksLikeSidebarHotelBlock({ rawText, className })) {
          current = current.parentElement
          continue
        }
        const priceSignals = extractPriceSignals(lines)
        const rawName = normalizeHotelName(rawText, href, className) || detectHotelNameFromLines(lines, href, className) || lines[0] || ""
        if (!looksLikeAggregateHotelBlock({ rawName, rawText, lines, priceSignals })) {
          const score = scoreHotelCard({ rawName, rawText, href, className, lines, priceSignals, hotelLinkCount: countLikelyHotelLinks(current) })
          if ((isLikelyHotelName(rawName, href, className) || (priceSignals.length && score >= 4)) && lines.length <= 18) {
            return current
          }
        }
      }
      current = current.parentElement
    }
    return null
  }

  function collectCandidateRows(requestedTargets = []) {
    const pageContext = detectPageContext()
    const domStructuredRows = collectStructuredListRowsFromDom()
    if (pageContext.pageType === "hotel_list" && domStructuredRows.length >= 3) {
      return domStructuredRows
    }

    const nodes = collectPreferredCandidateNodes(requestedTargets)
    const rows = []
    const rowOrder = []
    const rowIndexByName = new Map()
    for (const element of nodes) {
      const rawText = cleanText(String(element.innerText || element.textContent || ""))
      if (!rawText || rawText.length < 8 || rawText.length > 900) {
        continue
      }
      const href = resolveHref(element)
      if (looksLikeTransportText(rawText) || containsAnyKeyword(rawText, NON_HOTEL_KEYWORDS) || containsAnyKeyword(href, NON_HOTEL_KEYWORDS)) {
        continue
      }

      const lines = splitLines(rawText)
      const className = typeof element.className === "string" ? element.className : ""
      if (looksLikeSidebarHotelBlock({ rawText, className })) {
        continue
      }
      const hotelLinkCount = countLikelyHotelLinks(element)
      if (!lines.length || lines.length > 18 || hotelLinkCount > 5) {
        continue
      }
      const nameNode = element.querySelector?.('h1,h2,h3,h4,[class*="title"],[class*="name"],[class*="hotel"]')
      const rawName = normalizeHotelName(nameNode?.innerText || detectHotelNameFromLines(lines, href, className) || lines[0] || "", href, className)
      const priceSignals = extractPriceSignals(lines)
      const bestPrice = pickBestPrice(priceSignals)
      const score = scoreHotelCard({ rawName, rawText, href, className, lines, priceSignals, hotelLinkCount })
      if (looksLikeAggregateHotelBlock({ rawName, rawText, lines, priceSignals })) {
        continue
      }
      const hasStrongNameSignal = isLikelyHotelName(rawName, href, className)
      if (!hasStrongNameSignal && !(bestPrice && score >= 6 && containsAnyKeyword(rawText, HOTEL_CONTEXT_KEYWORDS))) {
        continue
      }
      if (!rawName && !bestPrice && score < 2) {
        continue
      }

      upsertCandidateRow(rows, rowOrder, rowIndexByName, {
        name: rawName,
        text: lines.join("\n"),
        href,
        price: bestPrice?.value || null,
        price_text: bestPrice?.raw || "",
        price_context: bestPrice?.line || "",
        price_score: bestPrice?.score ?? -99,
        price_signals: priceSignals.map((item) => item.raw),
        score,
        line_count: lines.length
      })
      if (rowOrder.length >= 200) {
        break
      }
    }

    mergeStructuredBodyRows(rows, rowOrder, rowIndexByName, domStructuredRows)
    if (!domStructuredRows.length) {
      mergeStructuredBodyRows(rows, rowOrder, rowIndexByName, collectStructuredListRowsFromBody())
    }

    if (!rows.length) {
      return collectFallbackRows()
    }
    return rowOrder.map((key) => rows[rowIndexByName.get(key)]).filter(Boolean)
  }

  function mergeStructuredBodyRows(rows, rowOrder, rowIndexByName, nextRows) {
    for (const row of Array.isArray(nextRows) ? nextRows : []) {
      upsertCandidateRow(rows, rowOrder, rowIndexByName, row)
      if (rowOrder.length >= 200) {
        break
      }
    }
  }

  function upsertCandidateRow(rows, rowOrder, rowIndexByName, candidate) {
    if (!candidate || typeof candidate !== "object") {
      return
    }
    const nameKey = normalizeMatchText(candidate.name || splitLines(candidate.text || "")[0] || "")
    const identityKey = nameKey || `${cleanText(candidate.href || "")}|${cleanText(candidate.text || "").slice(0, 80)}`
    if (!identityKey) {
      return
    }
    const existingIndex = rowIndexByName.get(identityKey)
    if (existingIndex === undefined) {
      rows.push(candidate)
      rowOrder.push(identityKey)
      rowIndexByName.set(identityKey, rows.length - 1)
      return
    }
    const existing = rows[existingIndex]
    if (scoreCandidateRow(candidate) > scoreCandidateRow(existing)) {
      rows[existingIndex] = candidate
    }
  }

  function scoreCandidateRow(row) {
    const price = Number(row?.price)
    const priceText = cleanText(row?.price_text || "")
    const priceContext = cleanText(row?.price_context || row?.text || "")
    const baseScore = Number.isFinite(Number(row?.score)) ? Number(row.score) : 0
    const priceScore = Number.isFinite(Number(row?.price_score)) ? Number(row.price_score) : -99
    let score = baseScore + Math.max(priceScore, -12)
    if (Number.isFinite(price) && price > 20) {
      score += 18
    }
    if (/^[¥￥]\s*\d/.test(priceText)) {
      score += 8
    }
    if (/(?:起|\/晚|每晚|含税|未税|到手|现价|促销价|低至|仅需)/.test(priceContext)) {
      score += 6
    }
    if (/(?:团购|券后|返现|红包|补贴)/.test(priceContext)) {
      score -= 4
    }
    if (/(?:米|公里|号|楼|层|室|分钟|小时前|天前)/.test(priceContext) && !/[¥￥]/.test(priceContext)) {
      score -= 8
    }
    return score
  }

  function collectFallbackRows() {
    const bodyText = String(document.body?.innerText || "")
    if (!bodyText) {
      return []
    }
    const lines = splitLines(bodyText).filter((line) => line.length <= 160)
    const rows = []
    const seen = new Set()
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index]
      const priceSignals = extractPriceSignals([line])
      const bestPrice = pickBestPrice(priceSignals)
      if (!bestPrice) {
        continue
      }
      let name = ""
      for (let offset = 1; offset <= 8; offset += 1) {
        const candidate = lines[index + offset]
        if (!candidate) {
          break
        }
        if (isLikelyHotelName(candidate, window.location.href, "")) {
          name = normalizeHotelName(candidate, window.location.href, "")
          break
        }
      }
      if (!name) {
        for (let offset = 1; offset <= 5; offset += 1) {
          const candidate = lines[index - offset]
          if (!candidate) {
            break
          }
          if (isLikelyHotelName(candidate, window.location.href, "")) {
            name = normalizeHotelName(candidate, window.location.href, "")
            break
          }
        }
      }
      if (!name) {
        continue
      }
      const rawText = [name, ...lines.slice(index, index + 4)].join(" ")
      const key = `${normalizeMatchText(name)}|${bestPrice.value}`
      if (seen.has(key)) {
        continue
      }
      seen.add(key)
      rows.push({
        name,
        text: rawText,
        href: window.location.href,
        price: bestPrice.value,
        price_text: bestPrice.raw,
        price_context: bestPrice.line,
        price_score: bestPrice.score,
        price_signals: priceSignals.map((item) => item.raw),
        score: 2,
        line_count: 1
      })
      if (rows.length >= 80) {
        break
      }
    }
    return rows
  }

  function collectStructuredListRowsFromBody() {
    const bodyText = String(document.body?.innerText || "")
    if (!bodyText) {
      return []
    }
    const lines = String(bodyText).split(/\n+/).map((line) => cleanText(line)).filter(Boolean)
    const rows = []
    const seen = new Set()
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index]
      if (!/^\d{1,3}$/.test(line)) {
        continue
      }
      const chunk = []
      for (let cursor = index + 1; cursor < Math.min(lines.length, index + 14); cursor += 1) {
        const nextLine = lines[cursor]
        if (!nextLine) {
          continue
        }
        if (cursor > index + 1 && /^\d{1,3}$/.test(nextLine)) {
          break
        }
        if (/^(?:上一页|下一页|到第\d+页)/.test(nextLine)) {
          break
        }
        chunk.push(nextLine)
      }
      if (!chunk.length) {
        continue
      }

      const name = chunk.find((item) => isLikelyHotelName(item, window.location.href, "") && !looksLikeSidebarHotelBlock({ rawText: item, className: "" }))
      if (!name) {
        continue
      }

      const priceChoice = pickPreferredStructuredPrice(chunk)
      if (!priceChoice) {
        continue
      }

      const key = `${normalizeMatchText(name)}|${priceChoice.value}`
      if (!key || seen.has(key)) {
        continue
      }
      seen.add(key)
      rows.push({
        name: trimMarketingSuffixes(name),
        text: chunk.join("\n"),
        href: window.location.href,
        price: priceChoice.value,
        price_text: priceChoice.raw,
        price_context: priceChoice.line,
        price_score: priceChoice.score + 4,
        price_signals: [priceChoice.raw],
        score: 6,
        line_count: chunk.length
      })
      if (rows.length >= 80) {
        break
      }
    }
    return rows
  }

  function collectStructuredListRowsFromDom() {
    const listRows = Array.from(document.querySelectorAll(".list-row.J_ListRow, .list-row.J_LazyZoom")).filter(Boolean)
    if (!listRows.length) {
      return []
    }

    const rows = []
    const seen = new Set()
    for (let index = 0; index < listRows.length; index += 1) {
      const currentRow = listRows[index]
      const nextRow = listRows[index + 1] || null
      const currentCenter = currentRow.querySelector?.(".row-center") || currentRow
      const titleAnchor = currentCenter?.querySelector?.(".row-title a")
      const titleNode = titleAnchor || currentCenter?.querySelector?.(".row-title")
      const rawName = cleanText((titleAnchor?.textContent || titleNode?.textContent || "").split("\n")[0] || "")
      const name = trimMarketingSuffixes(rawName)
      if (!name || !isLikelyHotelName(name, window.location.href, "")) {
        continue
      }

      const addressNode = currentCenter?.querySelector?.(".row-address")
      const bookedNode = currentCenter?.querySelector?.(".row-someone-book")
      const promoNode = currentCenter?.querySelector?.(".fan-icon")
      const currentText = [
        name,
        cleanText(promoNode?.textContent || ""),
        cleanText(addressNode?.textContent || ""),
        cleanText(bookedNode?.textContent || "")
      ].filter(Boolean)

      const currentPriceNode = currentRow.querySelector?.(".row-right .price, .row-right .box-price, .row-right .pi-price")
      const nextPriceNode = nextRow?.querySelector?.(".row-right .price, .row-right .box-price, .row-right .pi-price")
      const priceNode = currentPriceNode || nextPriceNode
      const reviewNode = currentRow.querySelector?.(".row-sub-right") || nextRow?.querySelector?.(".row-sub-right")
      const priceLine = cleanText(priceNode?.textContent || "")
      const reviewLine = cleanText(reviewNode?.textContent || "")
      const priceChoice = pickBestPrice(extractPriceSignals([priceLine]))
      if (!priceChoice) {
        continue
      }

      const key = `${normalizeMatchText(name)}|${priceChoice.value}`
      if (!key || seen.has(key)) {
        continue
      }
      seen.add(key)
      rows.push({
        name,
        text: [...currentText, priceLine, reviewLine].filter(Boolean).join("\n"),
        href: resolveHref(titleNode || currentCenter || currentRow) || window.location.href,
        price: priceChoice.value,
        price_text: priceChoice.raw,
        price_context: priceLine,
        price_score: (Number(priceChoice.score) || 0) + 6,
        price_signals: [priceChoice.raw],
        score: 8,
        line_count: currentText.length + (priceLine ? 1 : 0) + (reviewLine ? 1 : 0),
      })
      if (rows.length >= 120) {
        break
      }
    }
    return rows
  }

  function pickPreferredStructuredPrice(lines) {
    const candidates = []
    for (const line of Array.isArray(lines) ? lines : []) {
      if (!lineLooksLikePriceContext(line)) {
        continue
      }
      const best = pickBestPrice(extractPriceSignals([line]))
      if (!best) {
        continue
      }
      candidates.push(best)
    }
    if (!candidates.length) {
      return null
    }
    const filtered = candidates.filter((item) => !/(?:团购|券后|返现|红包|补贴)/.test(String(item.line || "")))
    return (filtered.length ? filtered : candidates)[0]
  }

  function resolveHref(element) {
    if (!element) {
      return ""
    }
    const directHref = typeof element.getAttribute === "function" ? cleanText(element.getAttribute("href")) : ""
    if (directHref && !directHref.toLowerCase().startsWith("javascript")) {
      return toAbsoluteUrl(directHref)
    }
    const link = element.closest?.("a[href]") || element.querySelector?.("a[href]")
    const nestedHref = cleanText(link?.getAttribute?.("href") || link?.href || "")
    if (nestedHref && !nestedHref.toLowerCase().startsWith("javascript")) {
      return toAbsoluteUrl(nestedHref)
    }
    return ""
  }

  function countLikelyHotelLinks(element) {
    if (!element || typeof element.querySelectorAll !== "function") {
      return 0
    }
    const links = Array.from(element.querySelectorAll("a[href]")).slice(0, 24)
    let count = 0
    for (const link of links) {
      const href = toAbsoluteUrl(link.getAttribute?.("href") || link.href || "")
      if (isLikelyHotelDetailHref(href) || containsAnyKeyword(href, ["hotel.fliggy.com", "jiudian"])) {
        count += 1
      }
    }
    return count
  }

  function isLikelyHotelDetailHref(href) {
    const value = String(href || "").toLowerCase()
    return value.includes("hotel_detail") || value.includes("/hotel/") || value.includes("item.htm?id=")
  }

  function looksLikeTransportText(value) {
    const text = cleanText(value)
    if (!text) {
      return false
    }
    if (containsAnyKeyword(text, NON_HOTEL_KEYWORDS)) {
      return true
    }
    if (/[\u4e00-\u9fff]{2,8}\s*[-\u2014]\s*[\u4e00-\u9fff]{2,8}\s*\d{2}\u6708\d{2}\u65e5\s*\d{2,5}/.test(text)) {
      return true
    }
    if (/[\u4e00-\u9fff]{2,8}\s*[-\u2014]\s*[\u4e00-\u9fff]{2,8}/.test(text) && /\d{2}\u6708\d{2}\u65e5/.test(text)) {
      return true
    }
    if (/(\u53bb\u7a0b|\u8fd4\u7a0b|\u51fa\u53d1|\u5230\u8fbe)\s*\d{1,2}:\d{2}/.test(text)) {
      return true
    }
    return false
  }

  function toAbsoluteUrl(value) {
    try {
      return new URL(value, window.location.href).toString()
    } catch (error) {
      return cleanText(value)
    }
  }

  function lineLooksLikePriceContext(line) {
    const text = cleanText(line)
    if (!text) {
      return false
    }
    if (/[¥￥]\s*\d/.test(text)) {
      return true
    }
    if (/\d{2,5}(?:\.\d{1,2})?\s*(?:元\/晚|元每晚|元起|每晚|\/晚|起|含税|未税|到手|现价|促销价|低至|仅需)/.test(text)) {
      return true
    }
    return /(?:低至|仅需|现价|促销价|到手)\s*[¥￥]?\s*\d{2,5}/.test(text)
  }

  function isLikelyAddressPrice(line, raw) {
    const text = cleanText(line)
    const value = String(raw || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    if (!text || !value) {
      return false
    }
    if (new RegExp(`${value}\s*(?:号|楼|层|室|米|公里|分钟|小时前|天前)`).test(text)) {
      return true
    }
    if (new RegExp(`(?:路|街|巷|大道|号楼|弄|地图|近)\s*${value}`).test(text)) {
      return true
    }
    return /\d{1,2}小时前|\d{1,2}分钟前|地图/.test(text) && !lineLooksLikePriceContext(text)
  }

  function extractPriceSignals(lines) {
    const normalizedLines = Array.isArray(lines) ? lines : [String(lines || "")]
    const rawMatches = []
    const seen = new Set()
    normalizedLines.forEach((line) => {
      const cleanLine = cleanText(line)
      if (!cleanLine) {
        return
      }
      for (const match of cleanLine.matchAll(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/g)) {
        pushPriceMatch(rawMatches, seen, cleanLine, cleanText(match[0]), Number(match[1]))
      }
      if (!lineLooksLikePriceContext(cleanLine)) {
        return
      }
      for (const match of cleanLine.matchAll(/(\d{2,5}(?:\.\d{1,2})?)\s*(?:元\/晚|元每晚|元起|元|起|每晚|\/晚|含税|未税|到手|现价|促销价|低至|仅需)?/g)) {
        pushPriceMatch(rawMatches, seen, cleanLine, cleanText(match[0]), Number(match[1]))
      }
    })
    const maxPrice = rawMatches.reduce((value, item) => Math.max(value, item.value), 0)
    return rawMatches
      .map((item) => ({ ...item, score: scorePriceSignal(item, maxPrice) }))
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score
        }
        return left.value - right.value
      })
      .slice(0, 12)
  }

  function pushPriceMatch(target, seen, line, raw, value) {
    if (!raw || !Number.isFinite(value) || value <= 20 || value > 50000) {
      return
    }
    if (isLikelyAddressPrice(line, raw)) {
      return
    }
    const key = `${raw}|${line}`
    if (seen.has(key)) {
      return
    }
    seen.add(key)
    target.push({ raw, value: Math.round(value * 100) / 100, line })
  }

  function scorePriceSignal(signal, maxPrice) {
    let score = 0
    const line = String(signal?.line || "")
    const price = Number(signal?.value || 0)
    if (containsAnyKeyword(line, PRICE_POSITIVE_HINTS)) {
      score += 3
    }
    if (containsAnyKeyword(line, HOTEL_CONTEXT_KEYWORDS)) {
      score += 1
    }
    if (containsAnyKeyword(line, PRICE_NEGATIVE_HINTS)) {
      score -= 4
    }
    if (/评分|公里|分钟|评价|已售|浏览/.test(line)) {
      score -= 2
    }
    if (price < 60 && maxPrice >= 120) {
      score -= 3
    }
    if (maxPrice && price > maxPrice * 1.6) {
      score -= 2
    }
    if (line.length >= 4 && line.length <= 32) {
      score += 1
    }
    if (/起\s*$/.test(line) || /每晚/.test(line)) {
      score += 2
    }
    if (/^[¥￥]\s*\d/.test(signal?.raw || "")) {
      score += 1
    }
    return score
  }

  function pickBestPrice(priceSignals) {
    if (!Array.isArray(priceSignals) || !priceSignals.length) {
      return null
    }
    return priceSignals[0]
  }

  function detectHotelNameFromLines(lines, href = "", className = "") {
    for (const line of lines) {
      if (isLikelyHotelName(line, href, className)) {
        return line
      }
    }
    return ""
  }


  function looksLikeAggregateHotelBlock({ rawName, rawText, lines, priceSignals }) {
    const name = cleanText(rawName)
    const text = cleanText(rawText)
    if (!text) {
      return false
    }
    if (containsAnyKeyword(name, AGGREGATE_HOTEL_BLOCK_KEYWORDS)) {
      return true
    }
    if (containsAnyKeyword(text, AGGREGATE_HOTEL_BLOCK_KEYWORDS) && (priceSignals.length >= 2 || lines.length >= 6)) {
      return true
    }
    const hotelKeywordHits = lines.filter((line) => containsAnyKeyword(line, HOTEL_KEYWORDS)).length
    if (priceSignals.length >= 2 && hotelKeywordHits >= 2 && text.length >= 60 && !href) {
      return true
    }
    return false
  }

  function looksLikeSidebarHotelBlock({ rawText, className }) {
    const text = cleanText(rawText)
    const classes = cleanText(className)
    if (!text && !classes) {
      return false
    }
    return containsAnyKeyword(text, SIDEBAR_HOTEL_BLOCK_KEYWORDS) || containsAnyKeyword(classes, SIDEBAR_HOTEL_CLASS_KEYWORDS)
  }

  function scoreHotelCard({ rawName, rawText, href, className, lines, priceSignals, hotelLinkCount = 0 }) {
    let score = 0
    if (pickBestPrice(priceSignals)) {
      score += 2
    }
    if (containsAnyKeyword(href, ["hotel", "jiudian"])) {
      score += 2
    }
    if (containsAnyKeyword(rawName, HOTEL_KEYWORDS)) {
      score += 2
    } else if (containsAnyKeyword(rawText, HOTEL_KEYWORDS)) {
      score += 1
    }
    if (containsAnyKeyword(rawText, HOTEL_CONTEXT_KEYWORDS)) {
      score += 1
    }
    if (containsAnyKeyword(className, ["hotel", "room", "price"])) {
      score += 1
    }
    if (lines.length >= 2 && lines.length <= 12) {
      score += 1
    }
    if (rawName && rawText.includes(rawName)) {
      score += 1
    }
    if (hotelLinkCount > 0 && hotelLinkCount <= 3) {
      score += 1
    }
    if (hotelLinkCount > 4) {
      score -= 2
    }
    if (looksLikeTransportText(rawText) || looksLikeTransportText(rawName)) {
      score -= 6
    }
    return score
  }

  function normalizeHotelName(raw, href = "", className = "") {
    const lines = splitLines(raw)
    for (const line of lines) {
      if (isLikelyHotelName(line, href, className)) {
        return trimMarketingSuffixes(line)
      }
    }
    return ""
  }

  function trimMarketingSuffixes(value) {
    let normalized = cleanText(stripInvisibleChars(value).replace(/[★☆◆◇●•※¤]+/g, " "))
    let previous = ""
    while (normalized && normalized !== previous) {
      previous = normalized
      for (const pattern of HOTEL_MARKETING_SUFFIX_PATTERNS) {
        normalized = cleanText(normalized.replace(pattern, "").replace(/[-|｜/·•~_]+$/g, ""))
      }
    }
    return normalized
  }

  function isLikelyHotelName(value, href = "", className = "") {
    const text = cleanText(value)
    if (!text || text.length < 4 || text.length > 80) {
      return false
    }
    if (looksLikeTransportText(text)) {
      return false
    }
    if (/[\uFFE5\u00A5]\d|\u5df2\u552e|\u9884\u8ba2|\u641c\u7d22|\u767b\u5f55|\u6ce8\u518c|\u5408\u4f5c|\u670d\u52a1|\u4e0b\u8f7d|\u6253\u5f00|\u626b\u7801|\u673a\u7968|\u822a\u73ed/.test(text)) {
      return false
    }
    if (containsAnyKeyword(text, AGGREGATE_HOTEL_BLOCK_KEYWORDS)) {
      return false
    }
    const looksLikeHotel = containsAnyKeyword(text, HOTEL_KEYWORDS)
    const looksLikeHotelLink = /hotel|jiudian|ebooking/i.test(String(href || "")) || /hotel|room|price/i.test(String(className || ""))
    if (looksLikeHotel) {
      return true
    }
    if (!looksLikeHotelLink) {
      return false
    }
    if (/\d{2}\u6708\d{2}\u65e5|\d{1,2}:\d{2}|\d{3,}/.test(text)) {
      return false
    }
    return text.length <= 36
  }

  function containsAnyKeyword(text, keywords) {
    const normalized = String(text || "").toLowerCase()
    return keywords.some((keyword) => normalized.includes(String(keyword).toLowerCase()))
  }

  function normalizeMatchText(value) {
    return trimMarketingSuffixes(value).toLowerCase().replace(/\s+/g, "")
  }

  function stripInvisibleChars(value) {
    return Array.from(String(value || "")).filter((char) => !/[\u0000-\u001F\u007F-\u009F\uE000-\uF8FF]/.test(char)).join("")
  }

  function splitLines(value) {
    return String(value || "").split(/\n+/).map((line) => cleanText(line)).filter(Boolean)
  }

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim()
  }

  function clampInt(value, fallback, minimum, maximum) {
    const next = Number(value)
    if (!Number.isFinite(next)) {
      return fallback
    }
    return Math.min(Math.max(Math.round(next), minimum), maximum)
  }

  function normalizeRequestedHotelNames(names) {
    if (!Array.isArray(names)) {
      return []
    }
    const result = []
    const seen = new Set()
    for (const item of names) {
      const text = cleanText(item)
      if (!text) {
        continue
      }
      const key = normalizeMatchText(text)
      if (!key || seen.has(key)) {
        continue
      }
      seen.add(key)
      result.push(text)
      if (result.length >= 5) {
        break
      }
    }
    return result
  }

  function createCandidateRowKey(row) {
    if (!row || typeof row !== "object") {
      return ""
    }
    const name = normalizeMatchText(row.name || "unknown")
    const href = cleanText(row.href || "")
    const price = Number.isFinite(Number(row.price)) ? Number(row.price).toFixed(2) : ""
    const text = cleanText(row.text || "").slice(0, 160)
    return name + "|" + href + "|" + price + "|" + text
  }

  function mergeCandidateRows(targetRows, nextRows, maxRows = 600) {
    const rows = Array.isArray(targetRows) ? targetRows : []
    const seen = new Set(rows.map((row) => createCandidateRowKey(row)).filter(Boolean))
    for (const row of Array.isArray(nextRows) ? nextRows : []) {
      const key = createCandidateRowKey(row)
      if (!key || seen.has(key)) {
        continue
      }
      seen.add(key)
      rows.push(row)
      if (rows.length >= maxRows) {
        break
      }
    }
    return rows
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms))
  }

  function getPageHeight() {
    return Math.max(
      Number(document.body?.scrollHeight || 0),
      Number(document.documentElement?.scrollHeight || 0),
      Number(document.scrollingElement?.scrollHeight || 0),
      Number(window.innerHeight || 0)
    )
  }

  async function collectRowsWithAutoScroll(requestedTargets = []) {
    const mergedRows = []
    const originalScrollY = Number(window.scrollY || 0)
    let lastHeight = 0
    let stableRounds = 0
    const stepSize = Math.max(Math.floor(Number(window.innerHeight || 900) * 0.85), 720)

    window.scrollTo(0, 0)
    await delay(280)

    for (let step = 0; step < 14; step += 1) {
      mergeCandidateRows(mergedRows, collectCandidateRows(requestedTargets))
      const height = getPageHeight()
      const targetY = Math.min(step * stepSize, Math.max(0, height - Number(window.innerHeight || 0)))
      window.scrollTo(0, targetY)
      await delay(step < 2 ? 450 : 650)
      mergeCandidateRows(mergedRows, collectCandidateRows(requestedTargets))

      const nextHeight = getPageHeight()
      const nearBottom = Number(window.scrollY || 0) + Number(window.innerHeight || 0) >= nextHeight - 140
      stableRounds = Math.abs(nextHeight - lastHeight) < 40 ? stableRounds + 1 : 0
      lastHeight = nextHeight
      if (nearBottom && stableRounds >= 2) {
        break
      }
    }

    window.scrollTo(0, originalScrollY)
    await delay(180)
    mergeCandidateRows(mergedRows, collectCandidateRows(requestedTargets))
    return mergedRows
  }

  function isVisibleElement(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false
    }
    const rect = element.getBoundingClientRect()
    return rect.width > 0 && rect.height > 0
  }

  function isDisabledPaginationControl(element) {
    if (!element) {
      return true
    }
    const ariaDisabled = String(element.getAttribute?.("aria-disabled") || "").toLowerCase()
    const className = String(element.className || "").toLowerCase()
    return Boolean(element.disabled) || ariaDisabled === "true" || /disabled|forbid|ban/.test(className)
  }

  function resolvePaginationControl(element) {
    if (!element) {
      return null
    }
    if (element.matches?.("a, button, [role='button']")) {
      return element
    }
    return element.closest?.("a, button, [role='button']") || element.querySelector?.("a, button, [role='button']") || null
  }

  function detectPaginationMarker() {
    const currentNode = document.querySelector('[aria-current="page"], [class*="current"], [class*="active"]')
    const currentText = cleanText(currentNode?.textContent || currentNode?.getAttribute?.("aria-label") || "")
    return window.location.href + "|" + currentText
  }

  function findNextPageControl() {
    const preferredSelectors = [
      'a[title*="\u4e0b\u4e00\u9875"]',
      'button[title*="\u4e0b\u4e00\u9875"]',
      'a[aria-label*="\u4e0b\u4e00\u9875"]',
      'button[aria-label*="\u4e0b\u4e00\u9875"]',
      'li[class*="next"] a',
      'a[class*="next"]',
      'button[class*="next"]'
    ]

    for (const selector of preferredSelectors) {
      const control = resolvePaginationControl(document.querySelector(selector))
      if (control && isVisibleElement(control) && !isDisabledPaginationControl(control)) {
        return control
      }
    }

    const textTokens = ["\u4e0b\u4e00\u9875", "\u540e\u9875", "next"]
    const elements = Array.from(document.querySelectorAll('a, button, [role="button"], li, span')).slice(0, 300)
    for (const element of elements) {
      const control = resolvePaginationControl(element)
      if (!control || !isVisibleElement(control) || isDisabledPaginationControl(control)) {
        continue
      }
      const text = cleanText(control.innerText || control.textContent || control.getAttribute?.("title") || control.getAttribute?.("aria-label") || "").toLowerCase()
      if (!text) {
        continue
      }
      if (textTokens.some((token) => text.includes(String(token).toLowerCase()))) {
        return control
      }
    }

    return null
  }

  function triggerClick(element) {
    if (!element) {
      return false
    }
    element.scrollIntoView?.({ block: "center", inline: "center" })
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }))
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }))
    element.click?.()
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }))
    return true
  }

  async function goToNextListPage() {
    const control = findNextPageControl()
    if (!control) {
      return false
    }

    const previousUrl = window.location.href
    const previousMarker = detectPaginationMarker()
    const previousCount = collectCandidateRows().length
    window.scrollTo(0, 0)
    await delay(240)
    triggerClick(control)

    for (let attempt = 0; attempt < 18; attempt += 1) {
      await delay(attempt < 3 ? 500 : 700)
      const markerChanged = detectPaginationMarker() !== previousMarker
      const urlChanged = window.location.href !== previousUrl
      const rowCount = collectCandidateRows().length
      if (markerChanged || urlChanged || (attempt >= 4 && rowCount > 0 && rowCount !== previousCount)) {
        window.scrollTo(0, 0)
        await delay(420)
        return true
      }
    }

    return false
  }

  function findHotelSearchInput() {
    const selectors = [
      'input[placeholder*="\u5173\u952e\u8bcd"]',
      'input[placeholder*="\u9152\u5e97"]',
      'input[placeholder*="\u76ee\u7684\u5730/\u9152\u5e97"]',
      'input[placeholder*="\u76ee\u7684\u5730"]',
      'input[name*="keyword"]',
      'input[name*="search"]',
      'input[type="search"]'
    ]
    for (const selector of selectors) {
      const elements = Array.from(document.querySelectorAll(selector))
      for (const element of elements) {
        if (!element || element.disabled || element.readOnly || !isVisibleElement(element)) {
          continue
        }
        return element
      }
    }
    return null
  }

  function setNativeInputValue(element, value) {
    const nextValue = String(value || "")
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value")
    if (descriptor && typeof descriptor.set === "function") {
      descriptor.set.call(element, nextValue)
    } else {
      element.value = nextValue
    }
  }

  function dispatchInputEvents(element) {
    element.dispatchEvent(new Event("input", { bubbles: true }))
    element.dispatchEvent(new Event("change", { bubbles: true }))
  }

  function dispatchEnterKey(element) {
    const eventInit = { bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13 }
    element.dispatchEvent(new KeyboardEvent("keydown", eventInit))
    element.dispatchEvent(new KeyboardEvent("keypress", eventInit))
    element.dispatchEvent(new KeyboardEvent("keyup", eventInit))
  }

  function findSearchTriggerForInput(input) {
    const directForm = input.form
    if (directForm) {
      const submit = directForm.querySelector('button[type="submit"], input[type="submit"], button')
      if (submit && isVisibleElement(submit) && !isDisabledPaginationControl(submit)) {
        return submit
      }
    }

    const textTokens = ["\u641c\u7d22", "\u67e5\u8be2", "\u786e\u5b9a", "search"]
    let current = input.parentElement
    for (let depth = 0; current && depth < 4; depth += 1) {
      const candidates = Array.from(current.querySelectorAll('button, a, [role="button"], input[type="submit"]')).slice(0, 20)
      for (const candidate of candidates) {
        const text = cleanText(candidate.innerText || candidate.textContent || candidate.getAttribute?.("value") || candidate.getAttribute?.("title") || "").toLowerCase()
        if (!text || !isVisibleElement(candidate) || isDisabledPaginationControl(candidate)) {
          continue
        }
        if (textTokens.some((token) => text.includes(String(token).toLowerCase()))) {
          return candidate
        }
      }
      current = current.parentElement
    }
    return null
  }

  function stripHotelCityPrefix(value) {
    const normalized = trimMarketingSuffixes(value)
    const matched = normalized.match(/^[一-鿿]{2,4}(.*)$/)
    if (!matched) {
      return normalized
    }
    const candidate = cleanText(matched[1])
    if (candidate && containsAnyKeyword(candidate, HOTEL_KEYWORDS)) {
      return candidate
    }
    return normalized
  }

  function buildHotelMatchKeys(value) {
    const normalized = trimMarketingSuffixes(value)
    if (!normalized) {
      return []
    }
    const candidates = new Set([normalized])
    const withoutParen = cleanText(normalized.replace(/[\uFF08(][^\uFF08\uFF09()]{1,40}[)\uFF09]\s*$/, ""))
    if (withoutParen) {
      candidates.add(withoutParen)
    }
    for (const candidate of Array.from(candidates)) {
      const withoutCity = stripHotelCityPrefix(candidate)
      if (withoutCity) {
        candidates.add(withoutCity)
      }
    }
    return Array.from(candidates).map((item) => normalizeMatchText(item)).filter(Boolean)
  }

  function targetMatchesKeyword(leftValue, rightValue) {
    const leftKeys = buildHotelMatchKeys(leftValue)
    const rightKeys = buildHotelMatchKeys(rightValue)
    if (!leftKeys.length || !rightKeys.length) {
      return false
    }
    for (const left of leftKeys) {
      for (const right of rightKeys) {
        const shorter = Math.min(left.length, right.length)
        if (shorter < 2) {
          continue
        }
        if (left === right || left.includes(right) || (shorter >= 6 && right.includes(left))) {
          return true
        }
      }
    }
    return false
  }

  function targetExistsInRows(rows, targetName) {
    if (!targetName) {
      return false
    }
    for (const row of Array.isArray(rows) ? rows : []) {
      if (!row || typeof row !== "object") {
        continue
      }
      if (targetMatchesKeyword(row.name || "", targetName) || targetMatchesKeyword(row.text || "", targetName)) {
        return true
      }
    }
    return false
  }

  function detectSearchMarker() {
    const context = detectPageContext()
    const firstRow = collectCandidateRows()[0] || null
    return [window.location.href, context.keyword, createCandidateRowKey(firstRow)].join("|")
  }

  async function searchHotelInCurrentList(targetName) {
    const input = findHotelSearchInput()
    if (!input || !targetName) {
      return { applied: false, reason: "search_input_missing" }
    }

    const previousMarker = detectSearchMarker()
    const previousRows = collectCandidateRows()
    input.focus()
    input.select?.()
    setNativeInputValue(input, targetName)
    dispatchInputEvents(input)
    await delay(160)

    const trigger = findSearchTriggerForInput(input)
    if (trigger) {
      triggerClick(trigger)
    } else {
      dispatchEnterKey(input)
    }

    for (let attempt = 0; attempt < 14; attempt += 1) {
      await delay(attempt < 3 ? 500 : 800)
      const markerChanged = detectSearchMarker() !== previousMarker
      const rows = collectCandidateRows()
      if (targetExistsInRows(rows, targetName)) {
        return { applied: true, matched: true }
      }
      if (markerChanged && rows.length && createCandidateRowKey(rows[0]) !== createCandidateRowKey(previousRows[0])) {
        return { applied: true, matched: false }
      }
    }

    return { applied: true, matched: targetExistsInRows(collectCandidateRows(), targetName) }
  }

  async function collectRowsAcrossPages(maxPages, requestedTargets = []) {
    const mergedRows = []
    const pageUrls = []
    let pageCount = 0

    for (let pageIndex = 0; pageIndex < maxPages; pageIndex += 1) {
      const pageContext = detectPageContext()
      if (pageContext.startUrl && !pageUrls.includes(pageContext.startUrl)) {
        pageUrls.push(pageContext.startUrl)
      }
      const rows = await collectRowsWithAutoScroll(requestedTargets)
      mergeCandidateRows(mergedRows, rows, Math.max(240, maxPages * 220))
      pageCount += 1
      if (pageIndex >= maxPages - 1) {
        break
      }
      const moved = await goToNextListPage()
      if (!moved) {
        break
      }
    }

    return { rows: mergedRows, pageUrls, pageCount }
  }

  async function collectPageSnapshot(options = {}) {
    const maxPages = clampInt(options.maxPages, 1, 1, 20)
    const requestedTargets = normalizeRequestedHotelNames(options.targetHotelNames)
    const initialContext = detectPageContext()
    const mergedRows = []
    const pageUrls = []
    const searchedTargets = []
    let totalPages = 0

    const shouldSearchTargets = Boolean(options.collectAllPages) && initialContext.pageType === "hotel_list" && requestedTargets.length > 0
    const targetBatches = shouldSearchTargets ? requestedTargets : [""]

    for (const targetName of targetBatches) {
      if (targetName) {
        const searchResult = await searchHotelInCurrentList(targetName)
        if (searchResult.applied) {
          searchedTargets.push(targetName)
        }
        await delay(420)
      }

      const batch = await collectRowsAcrossPages(maxPages, requestedTargets)
      mergeCandidateRows(mergedRows, batch.rows, Math.max(260, targetBatches.length * maxPages * 220))
      for (const pageUrl of batch.pageUrls) {
        if (pageUrl && !pageUrls.includes(pageUrl)) {
          pageUrls.push(pageUrl)
        }
      }
      totalPages += batch.pageCount
    }

    const finalContext = detectPageContext()
    return {
      pageContext: {
        ...initialContext,
        ...finalContext,
        targetHotelNames: requestedTargets.length ? requestedTargets : finalContext.targetHotelNames,
      },
      candidateRows: mergedRows,
      capturedAt: new Date().toLocaleString(),
      pageCount: totalPages || 1,
      pageUrls,
      searchedTargets
    }
  }

  window.FliggyOpsPageContext = { detectPageContext, collectPageSnapshot }
})()
