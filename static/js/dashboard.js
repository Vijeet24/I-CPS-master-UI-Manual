import { api } from "./api.js";
import { escapeHtml, formatDateTime, showToast, $ } from "./ui.js";

const state = {
  orders: [],
  metrics: null,
  mqttStatus: null,
  audit: [],
  asnTracking: [],
  selectedOrderId: null,
  selectedOrder: null,
  rfidScan: null,
  refreshTimer: null,
  ws: null,
};

const PIPELINE = [
  { key: "RECEIVED", label: "PO Received", icon: "01" },
  { key: "ACKNOWLEDGED", label: "PO Acknowledged", icon: "02" },
  { key: "PICKING", label: "Product Preparation", icon: "03" },
  { key: "ALLOCATED", label: "EPC Allocated", icon: "04" },
  { key: "VERIFIED", label: "RFID Verified", icon: "05" },
  { key: "ASN_SENT", label: "ASN Sent", icon: "06" },
];

const STATUS_ORDER = {
  RECEIVED: 1,
  ACKNOWLEDGED: 2,
  PICKING: 3,
  ALLOCATED: 4,
  VERIFIED: 5,
  ASN_SENT: 6,
};

const KPI_CONFIG = [
  { key: "purchase_orders_received", label: "POs Received", color: "#38bdf8" },
  { key: "po_acknowledgements_sent", label: "Acks Sent", color: "#fbbf24" },
  { key: "orders_in_preparation", label: "In Preparation", color: "#a78bfa" },
  { key: "rfid_verification_failures", label: "RFID Failures", color: "#f87171" },
  { key: "asn_sent", label: "ASN Sent", color: "#34d399" },
  { key: "total_products", label: "Products", color: "#818cf8" },
  { key: "total_epcs_available", label: "EPCs Available", color: "#2dd4bf" },
];

function updateClock() {
  const now = new Date();
  $("#dash-clock").textContent = now.toLocaleString(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function pickCurrentOrder(orders) {
  if (!orders.length) {
    return null;
  }
  const active = orders.find((order) => order.status !== "ASN_SENT");
  return active || orders[0];
}

function renderKpis() {
  const metrics = state.metrics || {};
  $("#dash-kpi-row").innerHTML = KPI_CONFIG.map(
    (kpi) => `
    <div class="kpi-card" style="--kpi-color:${kpi.color}">
      <span class="kpi-value">${metrics[kpi.key] ?? 0}</span>
      <span class="kpi-label">${escapeHtml(kpi.label)}</span>
    </div>`
  ).join("");
}

function renderMqttPill() {
  const status = state.mqttStatus;
  const dot = $("#dash-mqtt-dot");
  const text = $("#dash-mqtt-text");

  if (!status) {
    dot.className = "mqtt-dot offline";
    text.textContent = "MQTT unavailable";
    return;
  }

  if (!status.enabled) {
    dot.className = "mqtt-dot disabled";
    text.textContent = "MQTT disabled — simulation mode";
    return;
  }

  dot.className = status.connected ? "mqtt-dot online" : "mqtt-dot offline";
  text.textContent = status.connected
    ? `Live · ${status.subscribe_topic.split("/").pop()}`
    : `Offline · ${status.broker}`;
}

function renderOrderSelector() {
  const select = $("#order-selector");
  if (!state.orders.length) {
    select.innerHTML = '<option value="">No orders yet</option>';
    select.disabled = true;
    return;
  }

  select.disabled = false;
  select.innerHTML = state.orders
    .map(
      (order) => `
      <option value="${order.id}" ${order.id === state.selectedOrderId ? "selected" : ""}>
        ${escapeHtml(order.po_number)} · ${escapeHtml(order.status)}
      </option>`
    )
    .join("");
}

function renderHero() {
  const order = state.selectedOrder;
  if (!order) {
    $("#hero-po-number").textContent = "—";
    $("#hero-po-meta").textContent = "Simulate or receive a purchase order to begin monitoring.";
    $("#hero-status-chip").textContent = "Idle";
    $("#hero-status-chip").className = "hero-status-chip";
    $("#hero-buyer").textContent = "—";
    $("#hero-correlation").textContent = "—";
    $("#hero-received").textContent = "—";
    $("#hero-asn").textContent = "—";
    return;
  }

  const summary = state.orders.find((item) => item.id === order.id) || {};
  $("#hero-po-number").textContent = order.po_number;
  $("#hero-po-meta").textContent = `${order.epc_allocations?.length || summary.epc_count || 0} EPCs allocated · ${order.po_lines?.length || summary.line_item_count || 0} line items`;
  $("#hero-status-chip").textContent = order.status.replaceAll("_", " ");
  $("#hero-status-chip").className = `hero-status-chip status-${order.status.toLowerCase().replaceAll("_", "-")}`;
  $("#hero-buyer").textContent = order.buyer_id;
  $("#hero-correlation").textContent = order.correlation_message_id;
  $("#hero-received").textContent = formatDateTime(order.received_timestamp);
  $("#hero-asn").textContent = summary.asn_status || (order.shipment ? "SENT" : "PENDING");
}

function renderPipeline() {
  const order = state.selectedOrder;
  const track = $("#pipeline-track");

  if (!order) {
    track.innerHTML = PIPELINE.map(
      (step) => `
      <div class="pipeline-step pending">
        <div class="step-icon">${step.icon}</div>
        <div class="step-content"><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.key)}</span></div>
        <span class="step-time">—</span>
      </div>`
    ).join("");
    $("#pipeline-progress").textContent = "0 / 6";
    return;
  }

  const current = STATUS_ORDER[order.status] || 1;
  const stepsByStatus = Object.fromEntries(
    (order.workflow_steps || []).map((step) => [step.description, step])
  );

  track.innerHTML = PIPELINE.map((step) => {
    const stepOrder = STATUS_ORDER[step.key];
    let css = "pending";
    if (current > stepOrder) {
      css = "completed";
    } else if (current === stepOrder) {
      css = "active";
    }
    const workflow = stepsByStatus[step.key];
    const time = workflow?.timestamp ? formatDateTime(workflow.timestamp) : "—";
    return `
      <div class="pipeline-step ${css}">
        <div class="step-icon">${css === "completed" ? "✓" : step.icon}</div>
        <div class="step-content">
          <strong>${escapeHtml(step.label)}</strong>
          <span>${escapeHtml(step.key)}</span>
        </div>
        <span class="step-time">${time}</span>
      </div>`;
  }).join("");

  $("#pipeline-progress").textContent = `${Math.min(current, 6)} / 6`;
}

function renderLineItems() {
  const panel = $("#line-items-panel");
  const order = state.selectedOrder;
  if (!order) {
    panel.innerHTML = '<p class="empty-hint">No line items to display.</p>';
    return;
  }

  let lineItems = [];
  try {
    lineItems = JSON.parse(order.raw_po_json)?.payload?.line_items || [];
  } catch {
    lineItems = [];
  }

  if (!lineItems.length) {
    panel.innerHTML = '<p class="empty-hint">No line items found on this order.</p>';
    return;
  }

  panel.innerHTML = lineItems
    .map((item) => {
      const gtin = item.item_identification?.gtin_14;
      const epcs = (order.epc_allocations || []).filter((row) => row.gtin === gtin);
      return `
        <div class="line-item-row">
          <div>
            <strong>${escapeHtml(item.item_identification?.description || "Product")}</strong>
            <small>GTIN <code>${escapeHtml(gtin || "—")}</code></small>
            <div class="epc-tags" style="margin-top:0.45rem">
              ${
                epcs.length
                  ? epcs.map((row) => `<span class="epc-tag matched">${escapeHtml(row.epc)}</span>`).join("")
                  : '<span class="epc-tag">No EPCs allocated</span>'
              }
            </div>
          </div>
          <span class="qty-badge">× ${escapeHtml(item.quantity_ordered)}</span>
        </div>`;
    })
    .join("");
}

function renderEpcBlock(label, values, css = "") {
  if (!values?.length) {
    return `<div class="epc-block"><strong>${escapeHtml(label)}</strong><span class="empty-hint">None</span></div>`;
  }
  return `
    <div class="epc-block">
      <strong>${escapeHtml(label)}</strong>
      <div class="epc-tags">
        ${values.map((epc) => `<span class="epc-tag ${css}">${escapeHtml(epc)}</span>`).join("")}
      </div>
    </div>`;
}

function renderRfidPanel() {
  const panel = $("#rfid-panel");
  const actions = $("#rfid-actions");
  const pill = $("#rfid-result-pill");
  const order = state.selectedOrder;
  const scan = state.rfidScan;

  if (!order) {
    panel.innerHTML = '<p class="empty-hint">RFID data will appear when an order is allocated.</p>';
    actions.innerHTML = "";
    pill.textContent = "Pending";
    pill.className = "verification-pill";
    return;
  }

  const canScan = ["ALLOCATED", "VERIFIED"].includes(order.status);
  const canVerify = scan?.result === "PENDING";
  const canGenerateAsn = order.status === "VERIFIED";

  if (scan?.result === "PASS") {
    pill.textContent = "Pass";
    pill.className = "verification-pill pass";
  } else if (scan?.result === "FAIL") {
    pill.textContent = "Fail";
    pill.className = "verification-pill fail";
  } else {
    pill.textContent = "Pending";
    pill.className = "verification-pill";
  }

  const expected = scan?.expected_epcs || order.epc_allocations?.map((row) => row.epc) || [];
  panel.innerHTML = `
    ${renderEpcBlock("Expected EPCs", expected)}
    ${renderEpcBlock("Scanned EPCs", scan?.scanned_epcs)}
    ${renderEpcBlock("Matched EPCs", scan?.matched_epcs, "matched")}
    ${renderEpcBlock("Missing EPCs", scan?.missing_epcs, "missing")}
    ${renderEpcBlock("Unexpected EPCs", scan?.unexpected_epcs, "missing")}
  `;

  actions.innerHTML = `
    <button class="dash-btn dash-btn-accent" id="rfid-start-btn" ${canScan ? "" : "disabled"}>Start RFID Reader</button>
    <button class="dash-btn dash-btn-ghost" id="rfid-rescan-btn" ${canScan ? "" : "disabled"}>Re-Scan</button>
    <button class="dash-btn dash-btn-ghost" id="rfid-verify-btn" ${canVerify ? "" : "disabled"}>Verify</button>
    <button class="dash-btn dash-btn-accent" id="rfid-asn-btn" ${canGenerateAsn ? "" : "disabled"}>Generate ASN</button>
  `;

  $("#rfid-start-btn")?.addEventListener("click", () => runRfid(order.id, false));
  $("#rfid-rescan-btn")?.addEventListener("click", () => runRfid(order.id, true));
  $("#rfid-verify-btn")?.addEventListener("click", () => verifyRfid(order.id, scan?.scan_session_id));
  $("#rfid-asn-btn")?.addEventListener("click", () => generateAsn(order.id));
}

function renderMqttFeed() {
  const feed = $("#mqtt-feed");
  if (!state.audit.length) {
    feed.innerHTML = '<p class="empty-hint">No MQTT messages recorded yet.</p>';
    return;
  }

  feed.innerHTML = state.audit.slice(0, 8).map(
    (entry) => `
    <div class="mqtt-event">
      <div class="mqtt-event-head">
        <span class="mqtt-event-type">${escapeHtml(entry.message_type.replace("EDI_", ""))}</span>
        <span class="mqtt-event-time">${formatDateTime(entry.timestamp)}</span>
      </div>
      <div class="mqtt-event-meta">
        ${escapeHtml(entry.direction)} · ${escapeHtml(entry.status)} · ${escapeHtml(entry.topic || "—")}
      </div>
    </div>`
  ).join("");
}

function renderAsnTable() {
  const tbody = $("#asn-table tbody");
  if (!state.asnTracking.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">No ASN messages sent yet.</td></tr>';
    return;
  }

  tbody.innerHTML = state.asnTracking
    .map(
      (row) => `
      <tr>
        <td><code>${escapeHtml(row.asn_number || "—")}</code></td>
        <td>${escapeHtml(row.po_number)}</td>
        <td>${escapeHtml(row.carrier)}</td>
        <td>${formatDateTime(row.asn_sent_time)}</td>
        <td>${row.total_epcs}</td>
      </tr>`
    )
    .join("");
}

async function loadSelectedOrder(orderId) {
  if (!orderId) {
    state.selectedOrder = null;
    state.rfidScan = null;
    renderHero();
    renderPipeline();
    renderLineItems();
    renderRfidPanel();
    return;
  }

  const [order, scan] = await Promise.all([api.getOrder(orderId), api.getRfidResults(orderId)]);
  state.selectedOrderId = orderId;
  state.selectedOrder = order;
  state.rfidScan = scan;
  renderOrderSelector();
  renderHero();
  renderPipeline();
  renderLineItems();
  renderRfidPanel();
}

async function refreshDashboard() {
  const [orders, metrics, mqttStatus, audit, asnTracking] = await Promise.all([
    api.getOrders(),
    api.getDashboardMetrics(),
    api.getMqttStatus(),
    api.getMessageAudit(12),
    api.getAsnTracking(),
  ]);

  state.orders = orders;
  state.metrics = metrics;
  state.mqttStatus = mqttStatus;
  state.audit = audit;
  state.asnTracking = asnTracking;

  if (!state.selectedOrderId || !orders.some((order) => order.id === state.selectedOrderId)) {
    const current = pickCurrentOrder(orders);
    state.selectedOrderId = current?.id ?? null;
  }

  renderKpis();
  renderMqttPill();
  renderOrderSelector();
  renderMqttFeed();
  renderAsnTable();

  if (state.selectedOrderId) {
    await loadSelectedOrder(state.selectedOrderId);
  } else {
    await loadSelectedOrder(null);
  }
}

async function runRfid(orderId, rescan) {
  try {
    state.rfidScan = await api.startRfidScan(orderId, rescan);
    showToast(rescan ? "Re-scan started." : "RFID reader activated.");
    await loadSelectedOrder(orderId);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function verifyRfid(orderId, scanSessionId) {
  try {
    state.rfidScan = await api.verifyRfidScan(orderId, scanSessionId);
    showToast(
      state.rfidScan.result === "PASS" ? "Verification passed." : "Verification failed.",
      state.rfidScan.result !== "PASS"
    );
    await refreshDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function generateAsn(orderId) {
  try {
    await api.generateAsn(orderId);
    showToast("ASN generated successfully.");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function simulatePo() {
  try {
    const sample = await api.getSamplePurchaseOrder();
    sample.message_id = crypto.randomUUID();
    sample.payload.purchase_order.po_number = `PO-DASH-${Date.now()}`;
    const order = await api.simulatePurchaseOrder(sample);
    state.selectedOrderId = order.id;
    showToast("Purchase order simulated.");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  if (!$("#dash-auto-refresh").checked) {
    return;
  }
  state.refreshTimer = window.setInterval(() => {
    refreshDashboard().catch(() => {});
  }, 5000);
}

function stopAutoRefresh() {
  if (state.refreshTimer) {
    window.clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${protocol}://${window.location.host}/ws/events`);
  state.ws.onmessage = () => {
    refreshDashboard().catch(() => {});
  };
  state.ws.onclose = () => {
    window.setTimeout(connectWebSocket, 5000);
  };
}

function bindEvents() {
  $("#dash-refresh-btn").addEventListener("click", () => {
    refreshDashboard().catch((error) => showToast(error.message, true));
  });

  $("#dash-auto-refresh").addEventListener("change", startAutoRefresh);

  $("#order-selector").addEventListener("change", (event) => {
    const orderId = Number(event.target.value) || null;
    loadSelectedOrder(orderId).catch((error) => showToast(error.message, true));
  });

  $("#dash-simulate-btn").addEventListener("click", () => {
    simulatePo().catch((error) => showToast(error.message, true));
  });

  window.setInterval(updateClock, 1000);
  updateClock();
  startAutoRefresh();
  connectWebSocket();
}

async function init() {
  bindEvents();
  try {
    await refreshDashboard();
  } catch (error) {
    showToast(`Failed to load dashboard: ${error.message}`, true);
  }
}

init();
