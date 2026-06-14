async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 204) {
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
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
  getMessageAudit: (limit = 100) => apiRequest(`/api/orders/audit?limit=${limit}`),
  getWorkflowStats: () => apiRequest("/api/orders/stats"),
  getMqttStatus: () => apiRequest("/api/orders/mqtt-status"),
  getSamplePurchaseOrder: () => apiRequest("/api/orders/sample/purchase-order"),
  simulatePurchaseOrder: (payload) =>
    apiRequest("/api/orders/simulate", { method: "POST", body: JSON.stringify({ payload }) }),
  forceShipOrder: (id) => apiRequest(`/api/orders/${id}/ship`, { method: "POST" }),
  sendAuditMessage: (id) => apiRequest(`/api/orders/audit/${id}/send`, { method: "POST" }),
};
