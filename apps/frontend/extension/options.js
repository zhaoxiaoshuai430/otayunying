const form = document.getElementById("config-form");
const messageBox = document.getElementById("message");
const testBtn = document.getElementById("testBtn");
const hotelList = document.getElementById("competitor-hotels");
const addHotelBtn = document.getElementById("add-hotel-btn");
const manualRoomList = document.getElementById("manual-room-mappings");
const addManualRoomBtn = document.getElementById("add-manual-room-btn");
const authSummary = document.getElementById("auth-summary");
let currentConfig = null;

addHotelBtn.addEventListener("click", () => {
  appendHotelRow({ name: "", url: "" });
  syncHotelTitles();
});

addManualRoomBtn.addEventListener("click", () => {
  appendManualRoomRow({
    displayName: "",
    roomType: "",
    rateName: "标准价",
    currentPrice: "",
    competitorRoomNames: [],
    enabled: true,
  });
  syncManualRoomTitles();
});

hotelList.addEventListener("click", (event) => {
  const removeBtn = event.target.closest("[data-action='remove-hotel']");
  if (!removeBtn) {
    return;
  }
  removeBtn.closest(".hotel-item")?.remove();
  renderEmptyStateIfNeeded();
  syncHotelTitles();
});

manualRoomList.addEventListener("click", (event) => {
  const removeBtn = event.target.closest("[data-action='remove-manual-room']");
  if (!removeBtn) {
    return;
  }
  removeBtn.closest(".manual-room-item")?.remove();
  renderManualRoomEmptyStateIfNeeded();
  syncManualRoomTitles();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("保存中...");
  try {
    ensureAuthenticated();
    const payload = readForm();
    const savedConfig = await sendMessage({ type: "SAVE_CONFIG", payload });
    currentConfig = savedConfig;
    applyConfig(savedConfig);
    const hotelCount = Array.isArray(savedConfig?.competitorHotels) ? savedConfig.competitorHotels.length : 0;
    const manualRoomCount = Array.isArray(savedConfig?.manualRoomMappings) ? savedConfig.manualRoomMappings.length : 0;
    setMessage(`设置已保存，当前有效竞对酒店 ${hotelCount} 家，自定义房型 ${manualRoomCount} 条。`);
  } catch (error) {
    setMessage(`保存失败: ${error.message}`, true);
  }
});

testBtn.addEventListener("click", async () => {
  setMessage("连接测试中...");
  try {
    ensureAuthenticated();
    const payload = readForm();
    const savedConfig = await sendMessage({ type: "SAVE_CONFIG", payload });
    currentConfig = savedConfig;
    applyConfig(savedConfig);
    const status = await sendMessage({ type: "SERVICE_STATUS" });
    const hotelCount = Array.isArray(savedConfig?.competitorHotels) ? savedConfig.competitorHotels.length : 0;
    const manualRoomCount = Array.isArray(savedConfig?.manualRoomMappings) ? savedConfig.manualRoomMappings.length : 0;
    setMessage(`连接成功: ${status.plugin} 在线，当前有效竞对酒店 ${hotelCount} 家，自定义房型 ${manualRoomCount} 条。`);
  } catch (error) {
    setMessage(`连接失败: ${error.message}`, true);
  }
});

loadConfig();

async function loadConfig() {
  try {
    const config = await sendMessage({ type: "GET_CONFIG" });
    currentConfig = config;
    applyConfig(config);
  } catch (error) {
    setMessage(`配置读取失败: ${error.message}`, true);
  }
}

function applyConfig(config) {
  currentConfig = config;
  document.getElementById("baseUrl").value = config.baseUrl;
  document.getElementById("tenantId").value = config.tenantId;
  document.getElementById("shopId").value = config.shopId;
  document.getElementById("tenantId").disabled = true;
  document.getElementById("shopId").disabled = true;
  document.getElementById("debugUrl").value = config.debugUrl;
  document.getElementById("startUrl").value = config.startUrl;
  document.getElementById("latestPriceLimit").value = config.latestPriceLimit;
  document.getElementById("maxPages").value = config.maxPages;
  document.getElementById("maxHotels").value = config.maxHotels;
  document.getElementById("saveResult").checked = Boolean(config.saveResult);
  renderCompetitorHotels(Array.isArray(config.competitorHotels) ? config.competitorHotels : []);
  renderManualRoomMappings(Array.isArray(config.manualRoomMappings) ? config.manualRoomMappings : []);
  renderAuthSummary(config);
  setAuthDisabled(!Boolean(config?.authenticated));
}

function renderAuthSummary(config) {
  const authenticated = Boolean(config?.authenticated && config?.authUser && config?.currentShop);
  if (!authenticated) {
    authSummary.textContent = "当前未登录。请先回到插件 Popup 登录后，再来维护当前店铺的竞对酒店配置。";
    return;
  }

  const username = String(config?.authUser?.username || "").trim();
  const tenantId = String(config?.authUser?.tenant_id || config?.tenantId || "").trim();
  const shopName = String(config?.currentShop?.shop_name || "").trim();
  const shopId = String(config?.currentShop?.shop_id || config?.shopId || "").trim();
  const shopCount = Array.isArray(config?.shops) ? config.shops.length : 0;
  authSummary.textContent = `当前账号: ${username} | Tenant: ${tenantId} | 当前店铺: ${shopName} (${shopId}) | 可访问店铺: ${shopCount} 家`;
}

function setAuthDisabled(disabled) {
  addHotelBtn.disabled = disabled;
  addManualRoomBtn.disabled = disabled;
  testBtn.disabled = disabled;
  form.querySelector("button[type='submit']").disabled = disabled;
  form.querySelectorAll("#competitor-hotels input, #competitor-hotels button, #manual-room-mappings input, #manual-room-mappings textarea, #manual-room-mappings button").forEach((node) => {
    node.disabled = disabled;
  });
}

function ensureAuthenticated() {
  if (!Boolean(currentConfig?.authenticated)) {
    throw new Error("请先在插件 Popup 中登录，并选择当前店铺");
  }
}

function renderCompetitorHotels(items) {
  hotelList.innerHTML = "";
  const rows = Array.isArray(items) && items.length ? items : [{ name: "", url: "" }];
  rows.forEach((item) => appendHotelRow(item));
  renderEmptyStateIfNeeded();
  syncHotelTitles();
}

function appendHotelRow(item) {
  const row = document.createElement("div");
  row.className = "hotel-item";
  row.innerHTML = `
    <div class="hotel-item-head">
      <div class="hotel-item-title">竞对酒店</div>
      <button type="button" class="danger" data-action="remove-hotel">删除</button>
    </div>
    <div class="hotel-item-grid">
      <label>
        酒店名称
        <input type="text" data-field="name" placeholder="例如：杭州君悦酒店" value="${escapeHtmlAttr(item?.name || "")}">
      </label>
      <label>
        详情页 URL
        <input type="url" data-field="url" placeholder="https://hotel.fliggy.com/hotel_detail.htm?id=..." value="${escapeHtmlAttr(item?.url || "")}">
      </label>
    </div>
  `;
  hotelList.appendChild(row);
}

function renderEmptyStateIfNeeded() {
  const rows = Array.from(hotelList.querySelectorAll(".hotel-item"));
  if (rows.length) {
    const empty = hotelList.querySelector(".hotel-empty");
    if (empty) {
      empty.remove();
    }
    return;
  }
  const empty = document.createElement("div");
  empty.className = "hotel-empty";
  empty.textContent = "还没有竞对酒店配置，先新增一条。";
  hotelList.appendChild(empty);
}

function syncHotelTitles() {
  const rows = Array.from(hotelList.querySelectorAll(".hotel-item"));
  rows.forEach((row, index) => {
    const title = row.querySelector(".hotel-item-title");
    if (title) {
      title.textContent = `竞对酒店 ${index + 1}`;
    }
  });
}

function normalizeManualRoomTerms(value) {
  const rawItems = Array.isArray(value)
    ? value
    : String(value || "").split(/[\n,，;；]+/);
  const result = [];
  const seen = new Set();
  for (const rawItem of rawItems) {
    const item = String(rawItem || "").replace(/\s+/g, " ").trim();
    if (!item || seen.has(item)) {
      continue;
    }
    seen.add(item);
    result.push(item);
    if (result.length >= 20) {
      break;
    }
  }
  return result;
}

function renderManualRoomMappings(items) {
  manualRoomList.innerHTML = "";
  const rows = Array.isArray(items) && items.length
    ? items
    : [{ displayName: "", roomType: "", rateName: "标准价", currentPrice: "", competitorRoomNames: [], enabled: true }];
  rows.forEach((item) => appendManualRoomRow(item));
  renderManualRoomEmptyStateIfNeeded();
  syncManualRoomTitles();
}

function appendManualRoomRow(item) {
  const currentPrice = Number(item?.currentPrice ?? item?.current_price ?? 0);
  const competitorRoomNames = normalizeManualRoomTerms(item?.competitorRoomNames || item?.competitor_room_names).join("\n");
  const row = document.createElement("div");
  row.className = "manual-room-item";
  row.innerHTML = `
    <div class="manual-room-item-head">
      <div class="manual-room-item-title">我的房型</div>
      <button type="button" class="danger" data-action="remove-manual-room">删除</button>
    </div>
    <div class="manual-room-grid">
      <label>
        房型名称
        <input type="text" data-field="displayName" placeholder="例如：高级大床房" value="${escapeHtmlAttr(item?.displayName || item?.display_name || "")}">
      </label>
      <label>
        房型类型
        <input type="text" data-field="roomType" placeholder="例如：大床房" value="${escapeHtmlAttr(item?.roomType || item?.room_type || "")}">
      </label>
      <label>
        价型名
        <input type="text" data-field="rateName" placeholder="例如：标准价" value="${escapeHtmlAttr(item?.rateName || item?.rate_name || "标准价")}">
      </label>
      <label>
        当前价
        <input type="number" min="1" step="0.01" data-field="currentPrice" placeholder="例如：429" value="${Number.isFinite(currentPrice) && currentPrice > 0 ? escapeHtmlAttr(String(currentPrice)) : ""}">
      </label>
      <label class="full">
        竞对房型匹配词
        <textarea data-field="competitorRoomNames" rows="4" placeholder="每行一个，例如：&#10;高级大床房&#10;豪华大床房">${escapeHtmlText(competitorRoomNames)}</textarea>
      </label>
      <label class="checkbox full">
        <input type="checkbox" data-field="enabled" ${item?.enabled === false ? "" : "checked"}>
        启用这条房型映射
      </label>
    </div>
  `;
  manualRoomList.appendChild(row);
}

function renderManualRoomEmptyStateIfNeeded() {
  const rows = Array.from(manualRoomList.querySelectorAll(".manual-room-item"));
  if (rows.length) {
    const empty = manualRoomList.querySelector(".manual-room-empty");
    if (empty) {
      empty.remove();
    }
    return;
  }
  const empty = document.createElement("div");
  empty.className = "manual-room-empty";
  empty.textContent = "还没有自定义房型，先新增一条。";
  manualRoomList.appendChild(empty);
}

function syncManualRoomTitles() {
  const rows = Array.from(manualRoomList.querySelectorAll(".manual-room-item"));
  rows.forEach((row, index) => {
    const title = row.querySelector(".manual-room-item-title");
    if (title) {
      title.textContent = `我的房型 ${index + 1}`;
    }
  });
}

function parseCombinedHotelEntry(value) {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }
  const matched = text.match(/^(.+?)\s*[|｜]\s*(https?:\/\/\S+)$/i);
  if (!matched) {
    return null;
  }
  return {
    name: matched[1].trim(),
    url: matched[2].trim(),
  };
}

function readCompetitorHotels() {
  return Array.from(hotelList.querySelectorAll(".hotel-item"))
    .map((row) => {
      const name = row.querySelector("[data-field='name']")?.value?.trim() || "";
      const url = row.querySelector("[data-field='url']")?.value?.trim() || "";
      const combined = parseCombinedHotelEntry(name) || parseCombinedHotelEntry(url);
      if (combined) {
        return combined;
      }
      return { name, url };
    })
    .filter((item) => item.name || item.url)
    .filter((item) => item.name && item.url)
    .slice(0, 20);
}

function readManualRoomMappings() {
  return Array.from(manualRoomList.querySelectorAll(".manual-room-item"))
    .map((row) => {
      const displayName = row.querySelector("[data-field='displayName']")?.value?.trim() || "";
      const roomType = row.querySelector("[data-field='roomType']")?.value?.trim() || "";
      const rateName = row.querySelector("[data-field='rateName']")?.value?.trim() || "标准价";
      const currentPriceRaw = Number(row.querySelector("[data-field='currentPrice']")?.value || 0);
      const currentPrice = Number.isFinite(currentPriceRaw) && currentPriceRaw > 0
        ? Math.round(currentPriceRaw * 100) / 100
        : null;
      const competitorRoomNames = normalizeManualRoomTerms(row.querySelector("[data-field='competitorRoomNames']")?.value || "");
      const enabled = Boolean(row.querySelector("[data-field='enabled']")?.checked);
      if (!displayName || !currentPrice) {
        return null;
      }
      return {
        displayName,
        roomType,
        rateName,
        currentPrice,
        competitorRoomNames,
        enabled,
      };
    })
    .filter(Boolean)
    .slice(0, 50);
}

function readForm() {
  return {
    baseUrl: document.getElementById("baseUrl").value.trim(),
    debugUrl: document.getElementById("debugUrl").value.trim(),
    startUrl: document.getElementById("startUrl").value.trim(),
    latestPriceLimit: Number(document.getElementById("latestPriceLimit").value),
    maxPages: Number(document.getElementById("maxPages").value),
    maxHotels: Number(document.getElementById("maxHotels").value),
    saveResult: document.getElementById("saveResult").checked,
    competitorHotels: readCompetitorHotels(),
    manualRoomMappings: readManualRoomMappings(),
  };
}

function escapeHtmlAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeHtmlText(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function setMessage(message, isError = false) {
  messageBox.textContent = message;
  messageBox.style.color = isError ? "#b42318" : "#8d6542";
}

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Unknown extension error"));
        return;
      }
      resolve(response.data);
    });
  });
}