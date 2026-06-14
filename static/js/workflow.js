import { api } from "./api.js";
import { closeModal, escapeHtml, formatDateTime, openModal, showToast, $ } from "./ui.js";

const workflowState = {
  orders: [],
  audit: [],
  stats: null,
  mqttStatus: null,
  selectedOrderId: null,
  refreshTimer: null,
};

const STATUS_LABELS = {
  RECEIVED: "Received",
  ACKNOWLEDGED: "Acknowledged",
  READY_TO_SHIP: "Ready to ship",
  SHIPPED: "Shipped",
};

function statusBadge(status) {
  const css = status.toLowerCase().replaceAll("_", "-");
  return `<span class="status-badge status-${css}">${escapeHtml(STATUS_LABELS[status] || status)}</span>`;
}

function directionBadge(direction) {
  const css = direction.toLowerCase();
  return `<span class="direction-badge direction-${css}">${escapeHtml(direction)}</span>`;
}

function renderWorkflowStats() {
  const stats = workflowState.stats || {};
  $("#stat-total").textContent = stats.total ?? 0;
  $("#stat-received").textContent = stats.received ?? 0;
  $("#stat-acknowledged").textContent = stats.acknowledged ?? 0;
  $("#stat-ready").textContent = stats.ready_to_ship ?? 0;
  $("#stat-shipped").textContent = stats.shipped ?? 0;
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
      '<tr><td colspan="6" class="empty-state">No purchase orders yet. Simulate an EDI 850 or publish to the MQTT topic.</td></tr>';
    return;
  }

  tbody.innerHTML = workflowState.orders
    .map(
      (order) => `
      <tr>
        <td><strong>${escapeHtml(order.po_number)}</strong></td>
        <td><code>${escapeHtml(order.buyer_id)}</code></td>
        <td>${statusBadge(order.status)}</td>
        <td>${formatDateTime(order.received_timestamp)}</td>
        <td>${order.line_item_count}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="view-order" data-id="${order.id}">View</button>
        </td>
      </tr>`
    )
    .join("");
}

function renderAuditTable() {
  const tbody = $("#audit-table tbody");
  if (!workflowState.audit.length) {
    tbody.innerHTML =
      '<tr><td colspan="5" class="empty-state">No EDI messages recorded yet.</td></tr>';
    return;
  }

  tbody.innerHTML = workflowState.audit
    .map((entry) => {
      const canSend = entry.direction === "OUTBOUND" && entry.status !== "SENT";
      return `
      <tr>
        <td>${formatDateTime(entry.timestamp)}</td>
        <td><code>${escapeHtml(entry.message_type.replace("EDI_", ""))}</code></td>
        <td>${directionBadge(entry.direction)}</td>
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

function renderLineItems(rawPoJson) {
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
          <th>UoM</th>
        </tr>
      </thead>
      <tbody>
        ${lineItems
          .map(
            (item) => `
          <tr>
            <td>${escapeHtml(item.line_number ?? "—")}</td>
            <td><code>${escapeHtml(item.item_identification?.gtin_14 ?? "—")}</code></td>
            <td>${escapeHtml(item.item_identification?.description ?? "—")}</td>
            <td>${escapeHtml(item.quantity_ordered ?? "—")}</td>
            <td>${escapeHtml(item.unit_of_measure ?? "—")}</td>
          </tr>`
          )
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

async function openOrderDetail(orderId) {
  const order = await api.getOrder(orderId);
  workflowState.selectedOrderId = orderId;

  $("#order-detail-title").textContent = `Order ${order.po_number}`;
  const forceShipBtn = $("#force-ship-btn");
  forceShipBtn.hidden = order.status === "SHIPPED";
  forceShipBtn.dataset.id = orderId;

  const ackSection = order.acknowledgement
    ? `
      <section class="detail-section">
        <h4>EDI 855 Acknowledgement</h4>
        <p><strong>Message ID:</strong> <code>${escapeHtml(order.acknowledgement.message_id)}</code></p>
        <p><strong>Sent:</strong> ${formatDateTime(order.acknowledgement.timestamp)}</p>
        <pre class="json-view">${escapeHtml(prettyJson(order.acknowledgement.raw_855_json))}</pre>
      </section>`
    : "";

  const shipSection = order.shipment
    ? `
      <section class="detail-section">
        <h4>EDI 856 Advance Ship Notice</h4>
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
      <h4>Workflow Progress</h4>
      ${renderWorkflowTimeline(order.workflow_steps)}
    </section>

    <section class="detail-section">
      <h4>Line Items (850)</h4>
      ${renderLineItems(order.raw_po_json)}
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

export async function refreshWorkflow() {
  const [orders, audit, stats, mqttStatus] = await Promise.all([
    api.getOrders(),
    api.getMessageAudit(),
    api.getWorkflowStats(),
    api.getMqttStatus(),
  ]);
  workflowState.orders = orders;
  workflowState.audit = audit;
  workflowState.stats = stats;
  workflowState.mqttStatus = mqttStatus;
  renderWorkflowStats();
  renderMqttStatus();
  renderOrdersTable();
  renderAuditTable();
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
    await api.simulatePurchaseOrder(sample);
    showToast("Simulated EDI 850 processed. Acknowledgement generated; fulfillment scheduled.");
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
    await api.forceShipOrder(orderId);
    showToast("Shipment processing triggered.");
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

    if (button.dataset.action === "view-message") {
      openMessageDetail(Number(button.dataset.id));
      return;
    }

    if (button.dataset.action === "send-message") {
      sendAuditMessage(Number(button.dataset.id)).catch((error) =>
        showToast(error.message, true)
      );
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
