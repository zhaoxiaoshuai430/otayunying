const CLOUD_PROTOCOL_VERSION = "fliggy-ops-cloud-ui/v1"
const CLOUD_REQUEST_TYPE = "FLIGGY_OPS_CLOUD_REQUEST"
const CLOUD_RESPONSE_TYPE = "FLIGGY_OPS_CLOUD_RESPONSE"
const CLOUD_EVENT_TYPE = "FLIGGY_OPS_CLOUD_EVENT"
const REQUEST_TIMEOUT_MS = 300000

const hostNote = document.getElementById("host-note")
const statusDot = document.getElementById("status-dot")
const statusText = document.getElementById("status-text")
const resultBox = document.getElementById("result-box")
const settingsBtn = document.getElementById("settings-btn")
const serviceBtn = document.getElementById("service-btn")
const contextBtn = document.getElementById("context-btn")
const panelBtn = document.getElementById("panel-btn")
const roomPricesBtn = document.getElementById("room-prices-btn")
const adviceBtn = document.getElementById("advice-btn")
const merchantLoadBtn = document.getElementById("merchant-load-btn")
const merchantPreviewBtn = document.getElementById("merchant-preview-btn")
const totalRoomsInput = document.getElementById("total-rooms-input")
const availableRoomsInput = document.getElementById("available-rooms-input")
const currentPriceInput = document.getElementById("current-price-input")
const strategySelect = document.getElementById("strategy-select")

let readyHost = "unknown"

function updateStatus(message, type = "") {
  statusText.textContent = message
  statusDot.className = `dot ${type}`.trim()
}

function renderResult(value) {
  if (typeof value === "string") {
    resultBox.textContent = value
    return
  }
  resultBox.textContent = JSON.stringify(value, null, 2)
}

function toPositiveInteger(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next)
}

function toNonNegativeInteger(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next < 0) {
    return null
  }
  return Math.round(next)
}

function toPositiveNumber(value) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0) {
    return null
  }
  return Math.round(next * 100) / 100
}

function requestPlugin(action, payload = {}) {
  const requestId = `cloud-ui-${Date.now()}-${Math.random().toString(16).slice(2)}`
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", handleMessage)
      reject(new Error("插件桥请求超时"))
    }, REQUEST_TIMEOUT_MS)

    function handleMessage(event) {
      const data = event.data
      if (!data || data.protocol !== CLOUD_PROTOCOL_VERSION || data.type !== CLOUD_RESPONSE_TYPE || data.requestId !== requestId) {
        return
      }
      clearTimeout(timer)
      window.removeEventListener("message", handleMessage)
      if (!data.ok) {
        reject(new Error(String(data.error || "插件桥请求失败")))
        return
      }
      resolve(data.data)
    }

    window.addEventListener("message", handleMessage)
    window.parent.postMessage({
      protocol: CLOUD_PROTOCOL_VERSION,
      type: CLOUD_REQUEST_TYPE,
      requestId,
      action,
      payload
    }, "*")
  })
}

function runtime(type, payload = {}) {
  return requestPlugin("plugin.runtime", {
    message: {
      type,
      payload
    }
  })
}

async function runAction(label, action) {
  updateStatus(`${label}中...`)
  try {
    const result = await action()
    updateStatus(`${label}完成`, "ok")
    renderResult(result)
  } catch (error) {
    updateStatus(`${label}失败`, "error")
    renderResult(error instanceof Error ? error.message : String(error))
  }
}

function getInventoryPayload() {
  const totalRooms = toPositiveInteger(totalRoomsInput.value)
  const availableRooms = toNonNegativeInteger(availableRoomsInput.value)
  const currentPrice = toPositiveNumber(currentPriceInput.value)
  if (!totalRooms) {
    throw new Error("请先填写有效的总房量")
  }
  if (availableRooms === null) {
    throw new Error("请先填写有效的可售房量")
  }
  if (availableRooms > totalRooms) {
    throw new Error("可售房量不能大于总房量")
  }
  return {
    totalRooms,
    availableRooms,
    currentPrice: currentPrice || undefined,
    strategy: strategySelect.value || "balanced"
  }
}

function getInventorySnapshot() {
  const payload = getInventoryPayload()
  return {
    total_rooms: payload.totalRooms,
    available_rooms: payload.availableRooms,
    ...(payload.currentPrice ? { current_price: payload.currentPrice } : {})
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = String(button.dataset.view || "")
    document.querySelectorAll("[data-view]").forEach((item) => {
      item.classList.toggle("active", item === button)
    })
    document.querySelectorAll(".view").forEach((section) => {
      section.classList.toggle("active", section.id === `${view}-view`)
    })
  })
})

window.addEventListener("message", (event) => {
  const data = event.data
  if (!data || data.protocol !== CLOUD_PROTOCOL_VERSION || data.type !== CLOUD_EVENT_TYPE) {
    return
  }
  if (data.event === "plugin.ready") {
    readyHost = String(data.data?.host || "browser-extension")
    hostNote.textContent = readyHost === "extension-popup"
      ? "右上角插件已连接云端 UI"
      : "页面内助手已连接云端 UI"
    updateStatus("插件桥已连接", "ok")
  }
})

settingsBtn.addEventListener("click", () => {
  runAction("打开设置", () => runtime("OPEN_OPTIONS"))
})

serviceBtn.addEventListener("click", () => {
  runAction("检查服务", () => runtime("SERVICE_STATUS"))
})

contextBtn.addEventListener("click", () => {
  runAction("页面识别", () => requestPlugin("page.getContext"))
})

panelBtn.addEventListener("click", () => {
  runAction("打开页面面板", () => requestPlugin("panel.open"))
})

roomPricesBtn.addEventListener("click", () => {
  runAction("查看竞对价格", () => runtime("COMPETITOR_ROOM_PRICES_TABS", { saveResult: true }))
})

adviceBtn.addEventListener("click", () => {
  runAction("生成建议价", () => runtime("COMPETITOR_PRICING_ADVICE_PREVIEW", getInventoryPayload()))
})

merchantLoadBtn.addEventListener("click", () => {
  runAction("读取当前页房型价", () => runtime("MERCHANT_PRICING_ITEMS", { collectMode: "extension_current_tab" }))
})

merchantPreviewBtn.addEventListener("click", () => {
  runAction("生成房型建议价", () => runtime("COMPETITOR_WORKFLOW_PREVIEW", {
    refreshCompetitorPrices: true,
    inventorySnapshot: getInventorySnapshot(),
    strategy: strategySelect.value || "balanced"
  }))
})

updateStatus("等待插件桥连接")
window.setTimeout(() => {
  if (readyHost === "unknown") {
    updateStatus("未收到插件桥 ready 事件，仍可尝试操作", "error")
  }
}, 2500)
