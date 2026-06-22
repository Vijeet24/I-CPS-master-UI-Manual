import { api } from "./api.js";
import { bindWorkflowEvents, initWorkflow, refreshWorkflow } from "./workflow.js";
import {
  applyFormErrors,
  clearFormErrors,
  closeModal,
  confirmAction,
  escapeHtml,
  formatDateTime,
  formatPrice,
  openModal,
  showToast,
  $,
  $all,
} from "./ui.js";
import {
  isFormValid,
  validateBrandForm,
  validateCategoryForm,
  validateProductForm,
  validateSubcategoryForm,
} from "./validation.js";

const state = {
  products: [],
  filteredProducts: [],
  brands: [],
  categories: [],
  subcategories: [],
  pendingImportFile: null,
  editingProductId: null,
  editingBrandId: null,
  editingCategoryId: null,
  editingSubcategoryId: null,
};

function switchTab(tabName) {
  $all(".tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabName));
  $all(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `${tabName}-panel`));
  if (tabName === "orders") {
    refreshWorkflow().catch((error) => showToast(error.message, true));
  }
}

function getProductFormValues(form) {
  return {
    gtin_14: form.gtin_14.value.trim(),
    product_name: form.product_name.value.trim(),
    description: form.description.value.trim(),
    category_id: form.category_id.value || null,
    sub_category_id: form.sub_category_id.value || null,
    unit_of_measure: form.unit_of_measure.value.trim(),
    default_price: form.default_price.value.trim(),
    currency: form.currency.value.trim().toUpperCase(),
    brand_id: form.brand_id.value || null,
    gs1_digital_link: form.gs1_digital_link.value.trim(),
  };
}

function getBrandFormValues(form) {
  return {
    brand_name: form.brand_name.value.trim(),
    brand_gln: form.brand_gln.value.trim() || null,
    company_prefix: form.company_prefix.value.trim() || null,
    address: form.address.value.trim() || null,
  };
}

function getCategoryFormValues(form) {
  return { name: form.name.value.trim() };
}

function getSubcategoryFormValues(form) {
  return {
    name: form.name.value.trim(),
    category_id: form.category_id.value || null,
  };
}

function updateSaveButtonState(form, errors, buttonId) {
  const button = $(`#${buttonId}`);
  if (button) {
    button.disabled = !isFormValid(errors);
  }
}

function populateBrandSelect(select, selectedId = "") {
  select.innerHTML =
    '<option value="">Select Brand Name</option>' +
    state.brands
      .map(
        (brand) =>
          `<option value="${brand.id}" ${String(brand.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(brand.brand_name)}</option>`
      )
      .join("");
}

function populateCategorySelect(select, selectedId = "") {
  select.innerHTML =
    '<option value="">Select category (optional)</option>' +
    state.categories
      .map(
        (category) =>
          `<option value="${category.id}" ${String(category.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(category.name)}</option>`
      )
      .join("");
}

function populateSubcategorySelect(select, categoryId, selectedId = "") {
  const filtered = categoryId
    ? state.subcategories.filter((item) => String(item.category_id) === String(categoryId))
    : [];

  select.innerHTML =
    '<option value="">Select subcategory (optional)</option>' +
    filtered
      .map(
        (subcategory) =>
          `<option value="${subcategory.id}" ${String(subcategory.id) === String(selectedId) ? "selected" : ""}>${escapeHtml(subcategory.name)}</option>`
      )
      .join("");
  select.disabled = !categoryId;
}

function applyProductFilters() {
  const search = ($("#product-search")?.value || "").trim().toLowerCase();
  const categoryFilter = $("#product-category-filter")?.value || "";
  const brandFilter = $("#product-brand-filter")?.value || "";

  state.filteredProducts = state.products.filter((product) => {
    const matchesSearch =
      !search ||
      product.product_name.toLowerCase().includes(search) ||
      product.gtin_14.includes(search) ||
      (product.brand_name || "").toLowerCase().includes(search);
    const matchesCategory = !categoryFilter || String(product.category_id) === String(categoryFilter);
    const matchesBrand = !brandFilter || String(product.brand_id) === String(brandFilter);
    return matchesSearch && matchesCategory && matchesBrand;
  });
}

function populateProductFilters() {
  const categorySelect = $("#product-category-filter");
  const brandSelect = $("#product-brand-filter");
  if (!categorySelect || !brandSelect) {
    return;
  }

  const currentCategory = categorySelect.value;
  const currentBrand = brandSelect.value;
  categorySelect.innerHTML =
    '<option value="">All categories</option>' +
    state.categories
      .map(
        (category) =>
          `<option value="${category.id}" ${String(category.id) === currentCategory ? "selected" : ""}>${escapeHtml(category.name)}</option>`
      )
      .join("");
  brandSelect.innerHTML =
    '<option value="">All brands</option>' +
    state.brands
      .map(
        (brand) =>
          `<option value="${brand.id}" ${String(brand.id) === currentBrand ? "selected" : ""}>${escapeHtml(brand.brand_name)}</option>`
      )
      .join("");
}

function renderProductsTable() {
  applyProductFilters();
  const tbody = $("#products-table tbody");
  if (!state.filteredProducts.length) {
    tbody.innerHTML =
      '<tr><td colspan="8" class="empty-state">No products match the current filters.</td></tr>';
    return;
  }

  tbody.innerHTML = state.filteredProducts
    .map(
      (product) => `
      <tr>
        <td><code>${escapeHtml(product.gtin_14)}</code></td>
        <td>${escapeHtml(product.product_name)}</td>
        <td>${escapeHtml(product.brand_name)}</td>
        <td>${escapeHtml(product.category_path || "—")}</td>
        <td>${escapeHtml(product.unit_of_measure)}</td>
        <td>${formatPrice(product.default_price, product.currency)}</td>
        <td>${escapeHtml(product.currency)}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="edit-product" data-id="${product.id}">Edit</button>
          <button class="btn btn-danger" data-action="delete-product" data-id="${product.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

function renderBrandsTable() {
  const tbody = $("#brands-table tbody");
  if (!state.brands.length) {
    tbody.innerHTML =
      '<tr><td colspan="5" class="empty-state">No brands yet. Add your first brand.</td></tr>';
    return;
  }

  tbody.innerHTML = state.brands
    .map(
      (brand) => `
      <tr>
        <td>${escapeHtml(brand.brand_name)}</td>
        <td>${escapeHtml(brand.brand_gln || "—")}</td>
        <td>${escapeHtml(brand.company_prefix || "—")}</td>
        <td>${escapeHtml(brand.address || "—")}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="edit-brand" data-id="${brand.id}">Edit</button>
          <button class="btn btn-danger" data-action="delete-brand" data-id="${brand.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

function renderCategoriesTable() {
  const tbody = $("#categories-table tbody");
  if (!state.categories.length) {
    tbody.innerHTML =
      '<tr><td colspan="2" class="empty-state">No categories yet. Add your first category.</td></tr>';
    return;
  }

  tbody.innerHTML = state.categories
    .map(
      (category) => `
      <tr>
        <td>${escapeHtml(category.name)}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="edit-category" data-id="${category.id}">Edit</button>
          <button class="btn btn-danger" data-action="delete-category" data-id="${category.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

function renderSubcategoriesTable() {
  const tbody = $("#subcategories-table tbody");
  if (!state.subcategories.length) {
    tbody.innerHTML =
      '<tr><td colspan="3" class="empty-state">No subcategories yet. Add one under a parent category.</td></tr>';
    return;
  }

  const categoryMap = Object.fromEntries(state.categories.map((item) => [item.id, item.name]));
  tbody.innerHTML = state.subcategories
    .map(
      (subcategory) => `
      <tr>
        <td>${escapeHtml(subcategory.name)}</td>
        <td>${escapeHtml(categoryMap[subcategory.category_id] || "—")}</td>
        <td class="actions">
          <button class="btn btn-secondary" data-action="edit-subcategory" data-id="${subcategory.id}">Edit</button>
          <button class="btn btn-danger" data-action="delete-subcategory" data-id="${subcategory.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");
}

async function refreshAll() {
  const [products, brands, categories, subcategories] = await Promise.all([
    api.getProducts(),
    api.getBrands(),
    api.getCategories(),
    api.getSubcategories(),
  ]);
  state.products = products;
  state.brands = brands;
  state.categories = categories;
  state.subcategories = subcategories;
  populateProductFilters();
  renderProductsTable();
  renderBrandsTable();
  renderCategoriesTable();
  renderSubcategoriesTable();

  if ($("#orders-panel").classList.contains("active")) {
    await refreshWorkflow();
  }
}

function resetProductForm() {
  const form = $("#product-form");
  form.reset();
  state.editingProductId = null;
  $("#product-modal-title").textContent = "New Product";
  populateBrandSelect(form.brand_id);
  populateCategorySelect(form.category_id);
  populateSubcategorySelect(form.sub_category_id, "");
  clearFormErrors(form);
  updateSaveButtonState(form, validateProductForm(getProductFormValues(form)), "product-save-btn");
}

function openProductModal(product = null) {
  resetProductForm();
  const form = $("#product-form");

  if (product) {
    state.editingProductId = product.id;
    $("#product-modal-title").textContent = "Edit Product";
    form.gtin_14.value = product.gtin_14;
    form.product_name.value = product.product_name;
    form.description.value = product.description || "";
    form.unit_of_measure.value = product.unit_of_measure;
    form.default_price.value = product.default_price ?? "";
    form.currency.value = product.currency;
    form.gs1_digital_link.value = product.gs1_digital_link || "";
    populateBrandSelect(form.brand_id, product.brand_id);
    populateCategorySelect(form.category_id, product.category_id || "");
    populateSubcategorySelect(
      form.sub_category_id,
      product.category_id || "",
      product.sub_category_id || ""
    );
  }

  openModal("product-modal");
}

function resetBrandForm() {
  const form = $("#brand-form");
  form.reset();
  state.editingBrandId = null;
  $("#brand-modal-title").textContent = "Add Brand";
  clearFormErrors(form);
  updateSaveButtonState(form, validateBrandForm(getBrandFormValues(form)), "brand-save-btn");
}

function openBrandModal(brand = null) {
  resetBrandForm();
  const form = $("#brand-form");
  if (brand) {
    state.editingBrandId = brand.id;
    $("#brand-modal-title").textContent = "Edit Brand";
    form.brand_name.value = brand.brand_name;
    form.brand_gln.value = brand.brand_gln || "";
    form.company_prefix.value = brand.company_prefix || "";
    form.address.value = brand.address || "";
  }
  openModal("brand-modal");
}

function resetCategoryForm() {
  const form = $("#category-form");
  form.reset();
  state.editingCategoryId = null;
  $("#category-modal-title").textContent = "Add Category";
  clearFormErrors(form);
  updateSaveButtonState(form, validateCategoryForm(getCategoryFormValues(form)), "category-save-btn");
}

function openCategoryModal(category = null) {
  resetCategoryForm();
  const form = $("#category-form");
  if (category) {
    state.editingCategoryId = category.id;
    $("#category-modal-title").textContent = "Edit Category";
    form.name.value = category.name;
  }
  openModal("category-modal");
}

function resetSubcategoryForm() {
  const form = $("#subcategory-form");
  form.reset();
  state.editingSubcategoryId = null;
  $("#subcategory-modal-title").textContent = "Add Subcategory";
  populateCategorySelect(form.category_id);
  clearFormErrors(form);
  updateSaveButtonState(
    form,
    validateSubcategoryForm(getSubcategoryFormValues(form)),
    "subcategory-save-btn"
  );
}

function openSubcategoryModal(subcategory = null) {
  resetSubcategoryForm();
  const form = $("#subcategory-form");
  if (subcategory) {
    state.editingSubcategoryId = subcategory.id;
    $("#subcategory-modal-title").textContent = "Edit Subcategory";
    form.name.value = subcategory.name;
    populateCategorySelect(form.category_id, subcategory.category_id);
  }
  openModal("subcategory-modal");
}

async function saveProduct(event) {
  event.preventDefault();
  const form = $("#product-form");
  const values = getProductFormValues(form);
  const errors = validateProductForm(values);
  applyFormErrors(form, errors);
  updateSaveButtonState(form, errors, "product-save-btn");
  if (!isFormValid(errors)) {
    return;
  }

  const payload = {
    gtin_14: values.gtin_14,
    product_name: values.product_name,
    description: values.description || null,
    category_id: values.category_id ? Number(values.category_id) : null,
    sub_category_id: values.sub_category_id ? Number(values.sub_category_id) : null,
    unit_of_measure: values.unit_of_measure,
    default_price: values.default_price === "" ? null : Number(values.default_price),
    currency: values.currency,
    brand_id: Number(values.brand_id),
    gs1_digital_link: values.gs1_digital_link || null,
  };

  try {
    if (state.editingProductId) {
      await api.updateProduct(state.editingProductId, payload);
      showToast("Product updated.");
    } else {
      await api.createProduct(payload);
      showToast("Product created.");
    }
    closeModal("product-modal");
    await refreshAll();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveBrand(event) {
  event.preventDefault();
  const form = $("#brand-form");
  const values = getBrandFormValues(form);
  const errors = validateBrandForm(values);
  applyFormErrors(form, errors);
  updateSaveButtonState(form, errors, "brand-save-btn");
  if (!isFormValid(errors)) {
    return;
  }

  try {
    if (state.editingBrandId) {
      await api.updateBrand(state.editingBrandId, values);
      showToast("Brand updated.");
    } else {
      await api.createBrand(values);
      showToast("Brand created.");
    }
    closeModal("brand-modal");
    await refreshAll();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveCategory(event) {
  event.preventDefault();
  const form = $("#category-form");
  const values = getCategoryFormValues(form);
  const errors = validateCategoryForm(values);
  applyFormErrors(form, errors);
  updateSaveButtonState(form, errors, "category-save-btn");
  if (!isFormValid(errors)) {
    return;
  }

  try {
    if (state.editingCategoryId) {
      await api.updateCategory(state.editingCategoryId, values);
      showToast("Category updated.");
    } else {
      await api.createCategory(values);
      showToast("Category created.");
    }
    closeModal("category-modal");
    await refreshAll();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveSubcategory(event) {
  event.preventDefault();
  const form = $("#subcategory-form");
  const values = getSubcategoryFormValues(form);
  const errors = validateSubcategoryForm(values);
  applyFormErrors(form, errors);
  updateSaveButtonState(form, errors, "subcategory-save-btn");
  if (!isFormValid(errors)) {
    return;
  }

  const payload = {
    name: values.name,
    category_id: Number(values.category_id),
  };

  try {
    if (state.editingSubcategoryId) {
      await api.updateSubcategory(state.editingSubcategoryId, payload);
      showToast("Subcategory updated.");
    } else {
      await api.createSubcategory(payload);
      showToast("Subcategory created.");
    }
    closeModal("subcategory-modal");
    await refreshAll();
  } catch (error) {
    showToast(error.message, true);
  }
}

function bindLiveValidation(formId, getValues, validateFn, buttonId) {
  const form = $(`#${formId}`);
  form.addEventListener("input", () => {
    const errors = validateFn(getValues(form));
    applyFormErrors(form, errors);
    updateSaveButtonState(form, errors, buttonId);
  });
  form.addEventListener("change", () => {
    const errors = validateFn(getValues(form));
    applyFormErrors(form, errors);
    updateSaveButtonState(form, errors, buttonId);
  });
}

function bindEvents() {
  $all(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  $("#new-product-btn").addEventListener("click", () => openProductModal());
  $("#new-brand-btn").addEventListener("click", () => openBrandModal());
  $("#new-category-btn").addEventListener("click", () => openCategoryModal());
  $("#new-subcategory-btn").addEventListener("click", () => openSubcategoryModal());
  $("#refresh-btn").addEventListener("click", () => refreshAll().catch((error) => showToast(error.message, true)));

  $("#product-search")?.addEventListener("input", renderProductsTable);
  $("#product-category-filter")?.addEventListener("change", renderProductsTable);
  $("#product-brand-filter")?.addEventListener("change", renderProductsTable);

  $("#export-products-btn")?.addEventListener("click", async () => {
    try {
      const csv = await api.exportProducts();
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "products.csv";
      link.click();
      URL.revokeObjectURL(url);
      showToast("Product catalog exported.");
    } catch (error) {
      showToast(error.message, true);
    }
  });

  $("#import-products-file")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    try {
      const preview = await api.previewProductImport(file);
      state.pendingImportFile = file;
      $("#import-preview-body").innerHTML = `
        <p><strong>Imported:</strong> ${preview.imported_count} &nbsp; <strong>Failed:</strong> ${preview.failed_count}</p>
        <div class="table-wrap">
          <table class="nested-table">
            <thead><tr><th>Row</th><th>GTIN</th><th>Product</th><th>Status</th><th>Errors</th></tr></thead>
            <tbody>
              ${preview.rows
                .map(
                  (row) => `
                <tr>
                  <td>${row.row_number}</td>
                  <td><code>${escapeHtml(row.data.gtin_14 || "—")}</code></td>
                  <td>${escapeHtml(row.data.product_name || "—")}</td>
                  <td>${row.valid ? "Valid" : "Invalid"}</td>
                  <td>${escapeHtml((row.errors || []).join(", ") || "—")}</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>`;
      $("#confirm-import-btn").disabled = preview.failed_count > 0;
      openModal("import-preview-modal");
    } catch (error) {
      showToast(error.message, true);
    }
  });

  $("#confirm-import-btn")?.addEventListener("click", async () => {
    if (!state.pendingImportFile) {
      return;
    }
    try {
      const result = await api.importProducts(state.pendingImportFile);
      showToast(`Imported ${result.imported_count} products.`);
      state.pendingImportFile = null;
      closeModal("import-preview-modal");
      await refreshAll();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  $("#view-epc-inventory-btn")?.addEventListener("click", async () => {
    try {
      const rows = await api.getEpcInventory();
      const tbody = $("#epc-inventory-table tbody");
      tbody.innerHTML = rows.length
        ? rows
            .map(
              (row) => `
            <tr>
              <td><code>${escapeHtml(row.epc)}</code></td>
              <td><code>${escapeHtml(row.gtin)}</code></td>
              <td>${escapeHtml(row.status)}</td>
              <td>${formatDateTime(row.last_updated)}</td>
            </tr>`
            )
            .join("")
        : '<tr><td colspan="4" class="empty-state">No EPC inventory records found.</td></tr>';
      openModal("epc-inventory-modal");
    } catch (error) {
      showToast(error.message, true);
    }
  });

  $("#product-form").addEventListener("submit", saveProduct);
  $("#brand-form").addEventListener("submit", saveBrand);
  $("#category-form").addEventListener("submit", saveCategory);
  $("#subcategory-form").addEventListener("submit", saveSubcategory);

  $("#product-form").category_id.addEventListener("change", (event) => {
    const form = $("#product-form");
    populateSubcategorySelect(form.sub_category_id, event.target.value, "");
    const errors = validateProductForm(getProductFormValues(form));
    applyFormErrors(form, errors);
    updateSaveButtonState(form, errors, "product-save-btn");
  });

  $all("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.closeModal));
  });

  bindLiveValidation("product-form", getProductFormValues, validateProductForm, "product-save-btn");
  bindLiveValidation("brand-form", getBrandFormValues, validateBrandForm, "brand-save-btn");
  bindLiveValidation("category-form", getCategoryFormValues, validateCategoryForm, "category-save-btn");
  bindLiveValidation(
    "subcategory-form",
    getSubcategoryFormValues,
    validateSubcategoryForm,
    "subcategory-save-btn"
  );

  document.body.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) {
      return;
    }

    const id = Number(button.dataset.id);
    const action = button.dataset.action;

    if (action === "edit-product") {
      const product = state.products.find((item) => item.id === id);
      openProductModal(product);
      return;
    }

    if (action === "delete-product") {
      const product = state.products.find((item) => item.id === id);
      if (!product) {
        return;
      }
      if (
        !confirmAction(
          `Delete product "${product.product_name}" (GTIN ${product.gtin_14})? This cannot be undone.`
        )
      ) {
        return;
      }
      try {
        await api.deleteProduct(id);
        showToast("Product deleted.");
        await refreshAll();
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }

    if (action === "edit-brand") {
      openBrandModal(state.brands.find((item) => item.id === id));
      return;
    }

    if (action === "delete-brand") {
      const brand = state.brands.find((item) => item.id === id);
      if (!brand) {
        return;
      }
      if (!confirmAction(`Delete brand "${brand.brand_name}"? This cannot be undone.`)) {
        return;
      }
      try {
        await api.deleteBrand(id);
        showToast("Brand deleted.");
        await refreshAll();
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }

    if (action === "edit-category") {
      openCategoryModal(state.categories.find((item) => item.id === id));
      return;
    }

    if (action === "delete-category") {
      const category = state.categories.find((item) => item.id === id);
      if (!category) {
        return;
      }
      if (!confirmAction(`Delete category "${category.name}" and its subcategories?`)) {
        return;
      }
      try {
        await api.deleteCategory(id);
        showToast("Category deleted.");
        await refreshAll();
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }

    if (action === "edit-subcategory") {
      openSubcategoryModal(state.subcategories.find((item) => item.id === id));
      return;
    }

    if (action === "delete-subcategory") {
      const subcategory = state.subcategories.find((item) => item.id === id);
      if (!subcategory) {
        return;
      }
      if (!confirmAction(`Delete subcategory "${subcategory.name}"?`)) {
        return;
      }
      try {
        await api.deleteSubcategory(id);
        showToast("Subcategory deleted.");
        await refreshAll();
      } catch (error) {
        showToast(error.message, true);
      }
    }
  });
}

async function init() {
  bindEvents();
  bindWorkflowEvents();
  try {
    await Promise.all([refreshAll(), initWorkflow()]);
  } catch (error) {
    showToast(`Failed to load data: ${error.message}`, true);
  }
}

init();
