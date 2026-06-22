import { api } from "./api.js";
import { closeModal, escapeHtml, formatDateTime, openModal, showToast, $ } from "./ui.js";

const workflowState = {
  orders: [],
  audit: [],
  metrics: null,
  mqttStatus: null,
  asnTracking: [],
  selectedOrderId: null,
  selectedOrderDetail: null,
  refreshTimer: null,
  auditSearch: "",
};

const STATUS_LABELS = {
  RECEIVED: "Received",
  ACKNOWLEDGED: "Acknowledged",
  PICKING: "Picking",
  ALLOCATED: "Allocated",
  VERIFIED: "Verified",
  ASN_SENT: "ASN Sent",
};

const PIPELINE_STAGES = ["RECEIVED", "ACKNOWLEDGED", "PICKING", "ALLOCATED", "VERIFIED", "ASN_SENT"];

function statusBadge(status) {
  const css = status.toLowerCase().replaceAll("_", "-");
  return `<span class="status-badge status-${css}">${escapeHtml(STATUS_LABELS[status] || status)}</span>`;
}

function directionBadge(direction) {
  const css = direction.toLowerCase();
  return `<span class="direction-badge direction-${css}">${escapeHtml(direction)}</span>`;
}

function verificationBadge(result) {
  if (!result) {
    return '<span class="muted-text">—</span>';
  }
  const css = result === "PASS" ? "pass" : "fail";
  return `<span class="verification-badge verification-${css}">${escapeHtml(result)}</span>`;
}

function renderDashboardKpis() {
  const metrics = workflowState.metrics || {};
  $("#kpi-po-received").textContent = metrics.purchase_orders_received ?? 0;
  $("#kpi-po-ack").textContent = metrics.po_acknowledgements_sent ?? 0;
  $("#kpi-preparation").textContent = metrics.orders_in_preparation ?? 0;
  $("#kpi-rfid-failures").textContent = metrics.rfid_verification_failures ?? 0;
  $("#kpi-asn-sent").textContent = metrics.asn_sent ?? 0;
  $("#kpi-products").textContent = metrics.total_products ?? 0;
  $("#kpi-epcs").textContent = metrics.total_epcs_available ?? 0;
}

function renderPipeline() {
  const pipeline = workflowState.metrics?.pipeline || {};
  $("#pipeline-bar").innerHTML = PIPELINE_STAGES.map((stage, index) => {
    const count = pipeline[stage] ?? 0;
    const arrow = index < PIPELINE_STAGES.length - 1 ? '<span class="pipeline-arrow">↓</span>' : "";
    return `
      <div class="pipeline-stage">
        <div class="pipeline-count">${count}</div>
        <div class="pipeline-label">${escapeHtml(STATUS_LABELS[stage] || stage)}</div>
        ${arrow}
      </div>`;
  }).join("");
}

function renderMqttStatus() {
  const status = workflowState.mqttStatus;
  const indicator = $("#mqtt-indicator");
  const text = $("#mqtt-status-text");

  if (!status) {
    text.textContent = "MQTT status unavailable";
    indicator.className = "mqtt-indicator offline";
    return;
  }

  if (!status.enabled) {
    text.textContent = "MQTT disabled (simulation mode only)";
    indicator.className = "mqtt-indicator disabled";
    return;
  }

  indicator.className = status.connected ? "mqtt-indicator online" : "mqtt-indicator offline";
  text.textContent = status.connected
    ? `MQTT connected — listening on ${status.subscribe_topic}`
    : `MQTT disconnected — broker ${status.broker}:${status.port}`;
}

function renderOrdersTable() {
  const tbody = $("#orders-table tbody");
  if (!workflowState.orders.length) {
    tbody.innerHTML =
      '<tr><td colspan="9" class="empty-state">No purchase orders yet. Simulate an EDI 850 or publish to the MQTT topic.</td></tr>';
    return;
  }

  tbody.innerHTML = workflowState.orders
    .map(
      (order) => `
      <tr data-order-id="${order.id}" class="${workflowState.selectedOrderId === order.id ? "selected-row" : ""}">
        <td><strong>${escapeHtml(order.po_number)}</strong></td>
        <td><code>${escapeHtml(order.buyer_id)}</code></td>
        <td>${statusBadge(order.status)}</td>
        <td>${order.gtin_count ?? order.line_item_count ?? 0}</td>
        <td>${order.epc_count ?? 0}</td>
        <td>${verificationBadge(order.verification_result)}</td>
        <td>${escapeHtml(order.asn_status || "PENDING")}</td>
        <td>${formatDateTime(order.received_timestamp)}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="view-order" data-id="${order.id}">View</button>
          <button class="btn btn-secondary" data-action="select-rfid" data-id="${order.id}">RFID</button>
        </td>
      </tr>`
    )
    .join("");
}

function renderAuditTable() {
  const tbody = $("#audit-table tbody");
  if (!workflowState.audit.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No MQTT messages recorded yet.</td></tr>';
    return;
  }

  tbody.innerHTML = workflowState.audit
    .map((entry) => {
      const canSend = entry.direction === "OUTBOUND" && entry.status !== "SENT";
      return `
      <tr>
        <td>${formatDateTime(entry.timestamp)}</td>
        <td>${directionBadge(entry.direction)}</td>
        <td><code>${escapeHtml(entry.topic || "—")}</code></td>
        <td><code>${escapeHtml(entry.message_type.replace("EDI_", ""))}</code></td>
        <td><code>${escapeHtml(entry.correlation_id || "—")}</code></td>
        <td>${escapeHtml(entry.status)}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="view-message" data-id="${entry.id}">Payload</button>
          ${
            canSend
              ? `<button class="btn btn-primary" data-action="send-message" data-id="${entry.id}">Send</button>`
              : ""
          }
        </td>
      </tr>`;
    })
    .join("");
}

function renderAsnTable() {
  const tbody = $("#asn-table tbody");
  if (!workflowState.asnTracking.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No ASN messages sent yet.</td></tr>';
    return;
  }

  tbody.innerHTML = workflowState.asnTracking
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

function renderEpcList(label, values) {
  if (!values?.length) {
    return `<p class="muted-text">${escapeHtml(label)}: none</p>`;
  }
  return `
    <div class="epc-list-block">
      <strong>${escapeHtml(label)}</strong>
      <ul>${values.map((epc) => `<li><code>${escapeHtml(epc)}</code></li>`).join("")}</ul>
    </div>`;
}

function renderRfidPanel(order, scan) {
  const panel = $("#rfid-panel");
  if (!order) {
    panel.innerHTML = '<p class="muted-text">Select an order to monitor RFID verification.</p>';
    return;
  }

  const canScan = ["ALLOCATED", "VERIFIED"].includes(order.status);
  const canVerify = scan && scan.result === "PENDING";
  const canGenerateAsn = order.status === "VERIFIED";

  panel.innerHTML = `
    <div class="rfid-header">
      <div>
        <strong>${escapeHtml(order.po_number)}</strong>
        ${statusBadge(order.status)}
      </div>
      <div class="actions">
        <button class="btn btn-primary" id="start-rfid-btn" ${canScan ? "" : "disabled"}>Start RFID Reader</button>
        <button class="btn btn-secondary" id="rescan-rfid-btn" ${canScan ? "" : "disabled"}>Re-Scan Package</button>
        <button class="btn btn-secondary" id="verify-rfid-btn" ${canVerify ? "" : "disabled"}>Verify Scan</button>
        <button class="btn btn-primary" id="generate-asn-btn" ${canGenerateAsn ? "" : "disabled"}>Generate ASN</button>
      </div>
    </div>
    <div class="verification-result ${scan?.result === "PASS" ? "result-pass" : scan?.result === "FAIL" ? "result-fail" : ""}">
      <strong>Verification Result:</strong>
      ${scan?.result && scan.result !== "PENDING" ? verificationBadge(scan.result) : '<span class="muted-text">Pending</span>'}
    </div>
    ${renderEpcList("Expected EPCs", scan?.expected_epcs || order.epc_allocations?.map((item) => item.epc))}
    ${renderEpcList("Scanned EPCs", scan?.scanned_epcs)}
    ${renderEpcList("Matched EPCs", scan?.matched_epcs)}
    ${renderEpcList("Missing EPCs", scan?.missing_epcs)}
    ${renderEpcList("Unexpected EPCs", scan?.unexpected_epcs)}
  `;

  $("#start-rfid-btn")?.addEventListener("click", () => runRfidScan(order.id, false));
  $("#rescan-rfid-btn")?.addEventListener("click", () => runRfidScan(order.id, true));
  $("#verify-rfid-btn")?.addEventListener("click", () => runRfidVerify(order.id, scan?.scan_session_id));
  $("#generate-asn-btn")?.addEventListener("click", () => runGenerateAsn(order.id));
}

function renderWorkflowTimeline(steps) {
  return `
    <div class="workflow-timeline">
      ${steps
        .map(
          (step) => `
        <div class="workflow-step ${step.status}">
          <div class="workflow-step-marker">${step.step}</div>
          <div class="workflow-step-content">
            <strong>${escapeHtml(step.name)}</strong>
            <span class="workflow-step-meta">${escapeHtml(step.description)}</span>
            ${
              step.timestamp
                ? `<span class="workflow-step-time">${formatDateTime(step.timestamp)}</span>`
                : ""
            }
          </div>
        </div>`
        )
        .join("")}
    </div>`;
}

function renderLineItems(rawPoJson, allocations = []) {
  let lineItems = [];
  try {
    lineItems = JSON.parse(rawPoJson)?.payload?.line_items || [];
  } catch {
    lineItems = [];
  }

  if (!lineItems.length) {
    return '<p class="muted-text">No line items found.</p>';
  }

  return `
    <table class="nested-table">
      <thead>
        <tr>
          <th>Line</th>
          <th>GTIN-14</th>
          <th>Description</th>
          <th>Qty</th>
          <th>Allocated EPCs</th>
        </tr>
      </thead>
      <tbody>
        ${lineItems
          .map((item) => {
            const gtin = item.item_identification?.gtin_14;
            const epcs = allocations.filter((row) => row.gtin === gtin).map((row) => row.epc);
            return `
          <tr>
            <td>${escapeHtml(item.line_number ?? "—")}</td>
            <td><code>${escapeHtml(gtin ?? "—")}</code></td>
            <td>${escapeHtml(item.item_identification?.description ?? "—")}</td>
            <td>${escapeHtml(item.quantity_ordered ?? "—")}</td>
            <td>${epcs.map((epc) => `<code>${escapeHtml(epc)}</code>`).join("<br>") || "—"}</td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

function prettyJson(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

async function selectRfidOrder(orderId) {
  workflowState.selectedOrderId = orderId;
  const [order, scan] = await Promise.all([api.getOrder(orderId), api.getRfidResults(orderId)]);
  workflowState.selectedOrderDetail = order;
  renderOrdersTable();
  renderRfidPanel(order, scan);
}

async function openOrderDetail(orderId) {
  const order = await api.getOrder(orderId);
  workflowState.selectedOrderId = orderId;
  workflowState.selectedOrderDetail = order;
  renderRfidPanel(order, order.rfid_scan);

  $("#order-detail-title").textContent = `Order ${order.po_number}`;
  const forceShipBtn = $("#force-ship-btn");
  forceShipBtn.hidden = order.status === "ASN_SENT";
  forceShipBtn.dataset.id = orderId;
  forceShipBtn.textContent = order.status === "VERIFIED" ? "Generate ASN" : "Complete RFID + ASN";

  const ackSection = order.acknowledgement
    ? `
      <section class="detail-section">
        <h4>PO Acknowledgement (855)</h4>
        <p><strong>Message ID:</strong> <code>${escapeHtml(order.acknowledgement.message_id)}</code></p>
        <p><strong>Sent:</strong> ${formatDateTime(order.acknowledgement.timestamp)}</p>
        <pre class="json-view">${escapeHtml(prettyJson(order.acknowledgement.raw_855_json))}</pre>
      </section>`
    : "";

  const shipSection = order.shipment
    ? `
      <section class="detail-section">
        <h4>Advance Ship Notice (856)</h4>
        <p><strong>ASN Number:</strong> <code>${escapeHtml(order.shipment.asn_number || "—")}</code></p>
        <p><strong>Shipment ID:</strong> <code>${escapeHtml(order.shipment.shipment_id)}</code></p>
        <p><strong>Carrier:</strong> ${escapeHtml(order.shipment.carrier)}</p>
        <p><strong>Tracking:</strong> <code>${escapeHtml(order.shipment.tracking_number)}</code></p>
        <p><strong>Ship date:</strong> ${formatDateTime(order.shipment.ship_date)}</p>
        <pre class="json-view">${escapeHtml(prettyJson(order.shipment.raw_856_json))}</pre>
      </section>`
    : "";

  $("#order-detail-body").innerHTML = `
    <div class="detail-grid">
      <div><strong>Status</strong>${statusBadge(order.status)}</div>
      <div><strong>Buyer GLN</strong><code>${escapeHtml(order.buyer_id)}</code></div>
      <div><strong>Seller GLN</strong><code>${escapeHtml(order.seller_id || "—")}</code></div>
      <div><strong>Correlation ID</strong><code>${escapeHtml(order.correlation_message_id)}</code></div>
      <div><strong>Received</strong>${formatDateTime(order.received_timestamp)}</div>
    </div>

    <section class="detail-section">
      <h4>Order Processing Pipeline</h4>
      ${renderWorkflowTimeline(order.workflow_steps)}
    </section>

    <section class="detail-section">
      <h4>Line Items & EPC Allocations</h4>
      ${renderLineItems(order.raw_po_json, order.epc_allocations)}
    </section>

    ${ackSection}
    ${shipSection}

    <section class="detail-section">
      <h4>Raw Purchase Order (850)</h4>
      <pre class="json-view">${escapeHtml(prettyJson(order.raw_po_json))}</pre>
    </section>`;

  openModal("order-detail-modal");
}

function openMessageDetail(entryId) {
  const entry = workflowState.audit.find((item) => item.id === entryId);
  if (!entry) {
    return;
  }
  $("#message-detail-title").textContent = `${entry.message_type} (${entry.direction})`;
  $("#message-detail-json").textContent = prettyJson(entry.payload);
  openModal("message-detail-modal");
}

async function runRfidScan(orderId, rescan) {
  try {
    const scan = await api.startRfidScan(orderId, rescan);
    showToast(rescan ? "Re-scan started." : "RFID reader activated.");
    await selectRfidOrder(orderId);
    renderRfidPanel(workflowState.selectedOrderDetail, scan);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function runRfidVerify(orderId, scanSessionId) {
  try {
    const scan = await api.verifyRfidScan(orderId, scanSessionId);
    showToast(scan.result === "PASS" ? "RFID verification passed." : "RFID verification failed.", scan.result !== "PASS");
    await refreshWorkflow();
    await selectRfidOrder(orderId);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function runGenerateAsn(orderId) {
  try {
    await api.generateAsn(orderId);
    showToast("ASN generated.");
    await refreshWorkflow();
    await selectRfidOrder(orderId);
  } catch (error) {
    showToast(error.message, true);
  }
}

export async function refreshWorkflow() {
  const [orders, audit, metrics, mqttStatus, asnTracking] = await Promise.all([
    api.getOrders(),
    api.getMessageAudit(100, workflowState.auditSearch),
    api.getDashboardMetrics(),
    api.getMqttStatus(),
    api.getAsnTracking(),
  ]);
  workflowState.orders = orders;
  workflowState.audit = audit;
  workflowState.metrics = metrics;
  workflowState.mqttStatus = mqttStatus;
  workflowState.asnTracking = asnTracking;
  renderDashboardKpis();
  renderPipeline();
  renderMqttStatus();
  renderOrdersTable();
  renderAuditTable();
  renderAsnTable();

  if (workflowState.selectedOrderId) {
    await selectRfidOrder(workflowState.selectedOrderId).catch(() => {});
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  if (!$("#orders-auto-refresh").checked) {
    return;
  }
  workflowState.refreshTimer = window.setInterval(() => {
    if (!$("#orders-panel").classList.contains("active")) {
      return;
    }
    refreshWorkflow().catch(() => {});
  }, 5000);
}

function stopAutoRefresh() {
  if (workflowState.refreshTimer) {
    window.clearInterval(workflowState.refreshTimer);
    workflowState.refreshTimer = null;
  }
}

async function simulatePurchaseOrder() {
  try {
    const sample = await api.getSamplePurchaseOrder();
    sample.message_id = crypto.randomUUID();
    sample.payload.purchase_order.po_number = `PO-SIM-${Date.now()}`;
    const order = await api.simulatePurchaseOrder(sample);
    showToast("Simulated EDI 850 processed through picking and EPC allocation.");
    workflowState.selectedOrderId = order.id;
    await refreshWorkflow();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function sendAuditMessage(auditId) {
  try {
    const result = await api.sendAuditMessage(auditId);
    if (result.status === "already_sent") {
      showToast("Message was already sent.");
    } else {
      showToast(`Outbound message sent${result.topic ? ` to ${result.topic}` : ""}.`);
    }
    await refreshWorkflow();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function forceShipOrder(orderId) {
  try {
    const order = await api.getOrder(orderId);
    if (order.status === "VERIFIED") {
      await api.generateAsn(orderId);
    } else {
      await api.startRfidScan(orderId);
      await api.verifyRfidScan(orderId);
      await api.generateAsn(orderId);
    }
    showToast("Order completed through RFID verification and ASN generation.");
    closeModal("order-detail-modal");
    await refreshWorkflow();
  } catch (error) {
    showToast(error.message, true);
  }
}

export function bindWorkflowEvents() {
  $("#simulate-po-btn").addEventListener("click", () => {
    simulatePurchaseOrder().catch((error) => showToast(error.message, true));
  });

  $("#orders-auto-refresh").addEventListener("change", startAutoRefresh);

  $("#mqtt-audit-search")?.addEventListener("input", (event) => {
    workflowState.auditSearch = event.target.value.trim();
    refreshWorkflow().catch(() => {});
  });

  $("#force-ship-btn").addEventListener("click", () => {
    const orderId = Number($("#force-ship-btn").dataset.id);
    if (orderId) {
      forceShipOrder(orderId).catch((error) => showToast(error.message, true));
    }
  });

  document.body.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) {
      return;
    }

    if (button.dataset.action === "view-order") {
      openOrderDetail(Number(button.dataset.id)).catch((error) => showToast(error.message, true));
      return;
    }

    if (button.dataset.action === "select-rfid") {
      selectRfidOrder(Number(button.dataset.id)).catch((error) => showToast(error.message, true));
      return;
    }

    if (button.dataset.action === "view-message") {
      openMessageDetail(Number(button.dataset.id));
      return;
    }

    if (button.dataset.action === "send-message") {
      sendAuditMessage(Number(button.dataset.id)).catch((error) => showToast(error.message, true));
    }
  });

  startAutoRefresh();
}

export async function initWorkflow() {
  try {
    await refreshWorkflow();
  } catch (error) {
    showToast(`Failed to load seller workflow: ${error.message}`, true);
  }
}
