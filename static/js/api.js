async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/csv")) {
    if (!response.ok) {
      throw new Error(response.statusText);
    }
    return response.text();
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "object" && detail?.message
        ? detail.message
        : Array.isArray(detail)
          ? detail.map((item) => item.msg || JSON.stringify(item)).join(", ")
          : detail || response.statusText;
    throw new Error(message);
  }

  return data;
}

export const api = {
  getProducts: () => apiRequest("/api/products"),
  getProduct: (id) => apiRequest(`/api/products/${id}`),
  createProduct: (payload) =>
    apiRequest("/api/products", { method: "POST", body: JSON.stringify(payload) }),
  updateProduct: (id, payload) =>
    apiRequest(`/api/products/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteProduct: (id) => apiRequest(`/api/products/${id}`, { method: "DELETE" }),
  exportProducts: () => apiRequest("/api/products/export"),
  previewProductImport: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiRequest("/api/products/import/preview", { method: "POST", body: formData });
  },
  importProducts: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiRequest("/api/products/import", { method: "POST", body: formData });
  },
  getEpcInventory: (gtin) => {
    const query = gtin ? `?gtin=${encodeURIComponent(gtin)}` : "";
    return apiRequest(`/api/products/epc-inventory${query}`);
  },

  getBrands: () => apiRequest("/api/brands"),
  createBrand: (payload) =>
    apiRequest("/api/brands", { method: "POST", body: JSON.stringify(payload) }),
  updateBrand: (id, payload) =>
    apiRequest(`/api/brands/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteBrand: (id) => apiRequest(`/api/brands/${id}`, { method: "DELETE" }),

  getCategories: () => apiRequest("/api/categories"),
  createCategory: (payload) =>
    apiRequest("/api/categories", { method: "POST", body: JSON.stringify(payload) }),
  updateCategory: (id, payload) =>
    apiRequest(`/api/categories/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCategory: (id) => apiRequest(`/api/categories/${id}`, { method: "DELETE" }),

  getSubcategories: (categoryId) => {
    const query = categoryId ? `?category_id=${categoryId}` : "";
    return apiRequest(`/api/subcategories${query}`);
  },
  createSubcategory: (payload) =>
    apiRequest("/api/subcategories", { method: "POST", body: JSON.stringify(payload) }),
  updateSubcategory: (id, payload) =>
    apiRequest(`/api/subcategories/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteSubcategory: (id) => apiRequest(`/api/subcategories/${id}`, { method: "DELETE" }),

  getOrders: () => apiRequest("/api/orders"),
  getOrder: (id) => apiRequest(`/api/orders/${id}`),
  getOrderAudit: (id) => apiRequest(`/api/orders/${id}/audit`),
  getMessageAudit: (limit = 100, search = "") => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (search) {
      params.set("search", search);
    }
    return apiRequest(`/api/mqtt/audit?${params.toString()}`);
  },
  getWorkflowStats: () => apiRequest("/api/orders/stats"),
  getDashboardMetrics: () => apiRequest("/api/dashboard/metrics"),
  getAsnTracking: () => apiRequest("/api/dashboard/asn-tracking"),
  getMqttStatus: () => apiRequest("/api/orders/mqtt-status"),
  getSamplePurchaseOrder: () => apiRequest("/api/orders/sample/purchase-order"),
  simulatePurchaseOrder: (payload) =>
    apiRequest("/api/orders/simulate", { method: "POST", body: JSON.stringify({ payload }) }),
  forceShipOrder: (id) => apiRequest(`/api/orders/${id}/ship`, { method: "POST" }),
  sendAuditMessage: (id) => apiRequest(`/api/orders/audit/${id}/send`, { method: "POST" }),

  startRfidScan: (orderId, rescan = false) =>
    apiRequest("/api/rfid/start-scan", {
      method: "POST",
      body: JSON.stringify({ order_id: orderId, rescan }),
    }),
  verifyRfidScan: (orderId, scanSessionId) =>
    apiRequest("/api/rfid/verify", {
      method: "POST",
      body: JSON.stringify({ order_id: orderId, scan_session_id: scanSessionId || null }),
    }),
  getRfidResults: (orderId) => apiRequest(`/api/rfid/results/${orderId}`),
  generateAsn: (orderId) =>
    apiRequest("/api/asn/generate", { method: "POST", body: JSON.stringify({ order_id: orderId }) }),
};
