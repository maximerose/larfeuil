// Quick Transaction Form Handler

function updateRequiredFields() {
  ["block-expense", "block-income", "block-transfer"].forEach((blockId) => {
    const block = document.getElementById(blockId);
    if (!block) return;

    const isHidden = block.classList.contains("hidden");
    const fields = block.querySelectorAll("select, input");

    fields.forEach((field) => {
      if (isHidden) {
        if (field.hasAttribute("required")) {
          field.removeAttribute("required");
          field.setAttribute("data-was-required", "true");
        }
      } else {
        if (field.getAttribute("data-was-required") === "true") {
          field.setAttribute("required", "required");
          field.removeAttribute("data-was-required");
        }
      }
    });
  });
}

function initQuickTransactionForm() {
  if (typeof initTomSelects === "function") {
    initTomSelects();
  }

  const configEl = document.getElementById("quick-tx-modal-config");
  const isEditMode = configEl ? configEl.dataset.isEdit === "true" : false;
  const initialTxType = configEl ? configEl.dataset.initialType : "EXPENSE";

  const displayAmountInput = document.getElementById("total_amount_display");
  const hiddenTotalAmountInput = document.getElementById("total_amount");
  const refundHint = document.getElementById("refund-hint");

  const categorySelect = document.querySelector('select[name="expense_category"]');
  const mainSelect = document.querySelector('select[name="expense_account"]') || document.querySelector('select[name="ui_main_account"]');
  const fallbackSelect = document.querySelector('select[name="tr_fallback_account"]') || document.querySelector('select[name="ui_fallback_account"]');
  const splitBreakdown = document.getElementById("tr-split-breakdown");
  const trAmountInput = document.getElementById("meal_voucher_amount_input");
  const hiddenTrAccountId = document.getElementById("meal_voucher_account_id");
  const hiddenTrAmount = document.getElementById("meal_voucher_amount");
  const trMaxBadge = document.getElementById("tr-max-badge");
  const formEl = document.getElementById("quick-transaction-form");

  function autoResizeAmount() {
    if (!displayAmountInput) return;
    const length = displayAmountInput.value.length || 4;
    displayAmountInput.style.width = `${length + 0.5}ch`;
  }

  function getTrAccount(accId) {
    if (!window.trAccountsInfo || !accId) return null;
    return window.trAccountsInfo.find((acc) => acc.id === accId);
  }

  window.updateTrLogic = function () {
    const txTypeEl = document.querySelector('input[name="tx_type"]:checked');
    if (!txTypeEl) return;
    const txType = txTypeEl.value;

    if (!mainSelect || !window.trAccountsInfo) return;

    const catId = categorySelect ? categorySelect.value : "";
    const isEligible = window.catTrMap && window.catTrMap[catId] === true;

    // 1. Activer / Désactiver les options TR proprement (ajout ou retrait dans TomSelect)
    window.trAccountsInfo.forEach((trAcc) => {
      const trId = trAcc.id;
      const canUseTr = txType === "EXPENSE" && isEligible && trAcc.remaining > 0;

      if (mainSelect.tomselect) {
        if (canUseTr) {
          // L'ajouter s'il manque
          if (!mainSelect.tomselect.options[trId]) {
            mainSelect.tomselect.addOption({ value: trId, text: trAcc.name });
          }
        } else {
          // Le retirer
          if (mainSelect.tomselect.getValue() === trId) {
            const firstValid = Object.keys(mainSelect.tomselect.options).find(
              (val) => val !== trId && val !== ""
            );
            mainSelect.tomselect.setValue(firstValid || "", true);
          }
          mainSelect.tomselect.removeOption(trId);
        }
      } else {
        const nativeOpt = mainSelect.querySelector(`option[value="${trId}"]`);
        if (nativeOpt) {
          nativeOpt.disabled = !canUseTr;
          nativeOpt.style.display = canUseTr ? "" : "none";
          if (!canUseTr && mainSelect.value === trId) mainSelect.value = "";
        }
      }
    });

    if (mainSelect.tomselect) mainSelect.tomselect.refreshOptions(false);

    // 2. Gestion de la ventilation si Swile est sélectionné
    const selectedAccId = mainSelect.value || (mainSelect.tomselect ? mainSelect.tomselect.getValue() : "");
    const selectedTrAcc = getTrAccount(selectedAccId);
    const totalAmount = parseFloat(hiddenTotalAmountInput ? hiddenTotalAmountInput.value : 0) || 0;

    if (txType === "EXPENSE" && selectedTrAcc) {
      const trRemaining = selectedTrAcc.remaining;

      if (totalAmount > trRemaining) {
        // Dépassement : afficher la ventilation
        if (splitBreakdown) splitBreakdown.classList.remove("hidden");
        if (trMaxBadge) trMaxBadge.textContent = `Plafond dispo: ${trRemaining.toFixed(2).replace('.', ',')} €`;

        if (trAmountInput && (!trAmountInput.value || parseFloat(trAmountInput.value) > trRemaining || parseFloat(trAmountInput.value) <= 0)) {
          trAmountInput.value = trRemaining.toFixed(2);
        }

        const currentTrAmount = Math.min(totalAmount, Math.max(0, parseFloat(trAmountInput ? trAmountInput.value : 0) || trRemaining));
        const remainingForFallback = totalAmount - currentTrAmount;

        const remDisplay = document.getElementById("tr-split-remaining-display");
        if (remDisplay) remDisplay.textContent = remainingForFallback.toFixed(2).replace('.', ',') + " €";

        mainSelect.name = "ui_main_account";
        if (fallbackSelect) fallbackSelect.name = "expense_account";

        // Sélection par défaut du relais
        if (fallbackSelect) {
          const fallbackVal = fallbackSelect.value;
          if (!fallbackVal || fallbackVal === selectedTrAcc.id) {
            const defaultFallbackId = selectedTrAcc.fallback_id || "";
            if (fallbackSelect.tomselect && defaultFallbackId) {
              fallbackSelect.tomselect.setValue(defaultFallbackId, true);
            } else if (defaultFallbackId) {
              fallbackSelect.value = defaultFallbackId;
            }
          }
        }

        if (hiddenTrAccountId) hiddenTrAccountId.value = selectedTrAcc.id;
        if (hiddenTrAmount) hiddenTrAmount.value = currentTrAmount.toFixed(2);

      } else {
        // Achat <= Plafond
        if (splitBreakdown) splitBreakdown.classList.add("hidden");

        mainSelect.name = "expense_account";
        if (fallbackSelect) fallbackSelect.name = "ui_fallback_account";

        if (hiddenTrAccountId) hiddenTrAccountId.value = selectedTrAcc.id;
        if (hiddenTrAmount) hiddenTrAmount.value = totalAmount.toFixed(2);
      }
    } else {
      // Compte classique
      if (splitBreakdown) splitBreakdown.classList.add("hidden");

      mainSelect.name = "expense_account";
      if (fallbackSelect) fallbackSelect.name = "ui_fallback_account";

      if (hiddenTrAccountId) hiddenTrAccountId.value = "";
      if (hiddenTrAmount) hiddenTrAmount.value = "0.00";
    }
  };

  // Soumission
  if (formEl) {
    formEl.addEventListener("submit", function () {
      const selectedTrAcc = getTrAccount(mainSelect ? mainSelect.value : null);
      const totalAmount = parseFloat(hiddenTotalAmountInput ? hiddenTotalAmountInput.value : 0) || 0;

      if (selectedTrAcc && totalAmount > selectedTrAcc.remaining && fallbackSelect) {
        const fallbackValue = fallbackSelect.value;
        if (fallbackValue && fallbackValue !== selectedTrAcc.id) {
          if (mainSelect.tomselect) {
            mainSelect.tomselect.setValue(fallbackValue, true);
          } else {
            mainSelect.value = fallbackValue;
          }
        }
      }
    });
  }

  window.updateTransferAccounts = function () {
    const sourceSelect = document.querySelector('select[name="source_account"]');
    const destSelect = document.querySelector('select[name="destination_account"]');
    if (!sourceSelect || !destSelect) return;

    const sourceVal = sourceSelect.value;
    const destVal = destSelect.value;

    if (destSelect.tomselect) {
      Object.keys(destSelect.tomselect.options).forEach((val) => {
        destSelect.tomselect.options[val].disabled = val !== "" && val === sourceVal;
      });
      destSelect.tomselect.refreshOptions(false);
    }
    if (sourceSelect.tomselect) {
      Object.keys(sourceSelect.tomselect.options).forEach((val) => {
        sourceSelect.tomselect.options[val].disabled = val !== "" && val === destVal;
      });
      sourceSelect.tomselect.refreshOptions(false);
    }
  };

  window.swapTransferAccounts = function (e) {
    if (e && e.preventDefault) e.preventDefault();
    const sourceSelect = document.querySelector('select[name="source_account"]');
    const destSelect = document.querySelector('select[name="destination_account"]');
    if (!sourceSelect || !destSelect) return;

    const tempSourceVal = sourceSelect.value;
    const tempDestVal = destSelect.value;

    if (sourceSelect.tomselect) {
      Object.keys(sourceSelect.tomselect.options).forEach((val) => (sourceSelect.tomselect.options[val].disabled = false));
      sourceSelect.tomselect.setValue(tempDestVal, true);
    }
    if (destSelect.tomselect) {
      Object.keys(destSelect.tomselect.options).forEach((val) => (destSelect.tomselect.options[val].disabled = false));
      destSelect.tomselect.setValue(tempSourceVal, true);
    }
    sourceSelect.dispatchEvent(new Event("change", { bubbles: true }));
  };

  window.toggleTxType = function () {
    const txTypeEl = document.querySelector('input[name="tx_type"]:checked');
    if (!txTypeEl) return;
    const type = txTypeEl.value;

    document.getElementById("block-expense")?.classList.toggle("hidden", type !== "EXPENSE");
    document.getElementById("block-income")?.classList.toggle("hidden", type !== "INCOME");
    document.getElementById("block-transfer")?.classList.toggle("hidden", type !== "TRANSFER");
    if (refundHint) refundHint.classList.toggle("hidden", type !== "EXPENSE");

    const imputationWrapper = document.getElementById("imputation-wrapper");
    if (imputationWrapper) {
      imputationWrapper.style.opacity = type === "TRANSFER" ? "0.3" : "1";
      imputationWrapper.style.pointerEvents = type === "TRANSFER" ? "none" : "auto";
    }

    window.updateTrLogic();
    updateRequiredFields();
  };

  if (categorySelect) {
    categorySelect.addEventListener("change", window.updateTrLogic);
    if (categorySelect.tomselect) categorySelect.tomselect.on("change", window.updateTrLogic);
  }

  document.body.addEventListener("change", function(e) {
      if (e.target.name === "expense_account" || e.target.name === "ui_main_account" || e.target.name === "tr_fallback_account" || e.target.name === "ui_fallback_account") {
          window.updateTrLogic();
      }
  });

  if (trAmountInput) {
    trAmountInput.addEventListener("input", window.updateTrLogic);
  }

  if (displayAmountInput) {
    displayAmountInput.addEventListener("input", () => {
      autoResizeAmount();
      updateRefundHint();
      window.updateTrLogic();
    });
  }

  const sourceSelect = document.querySelector('select[name="source_account"]');
  const destSelect = document.querySelector('select[name="destination_account"]');
  if (sourceSelect) sourceSelect.addEventListener("change", window.updateTransferAccounts);
  if (destSelect) destSelect.addEventListener("change", window.updateTransferAccounts);

  autoResizeAmount();
  window.updateTransferAccounts();

  if (isEditMode && initialTxType) {
    const radioToSelect = document.querySelector(`input[name="tx_type"][value="${initialTxType}"]`);
    if (radioToSelect) radioToSelect.checked = true;
  }

  window.toggleTxType();
  updateRequiredFields();
  updateRefundHint();
}

function toggleAmountSign() {
  const disp = document.getElementById("total_amount_display");
  if (!disp) return;
  disp.value = disp.value.startsWith("-") ? disp.value.slice(1) : "-" + disp.value;
  disp.dispatchEvent(new Event("input"));
}

function updateRefundHint() {
  const disp = document.getElementById("total_amount_display");
  const hintText = document.getElementById("refund-hint-text");
  const hintContainer = document.getElementById("refund-hint");
  if (!disp || !hintText || !hintContainer) return;

  const isNegative = disp.value.trim().startsWith("-");

  if (isNegative) {
    hintText.innerHTML = "Remboursement actif. Clic ou <strong>±</strong> pour repasser en montant positif.";
    hintContainer.className =
      "flex items-center justify-center gap-1.5 text-xs text-action-warning mt-2 transition-colors cursor-pointer hover:opacity-80 select-none font-medium";
  } else {
    hintText.innerHTML = "Clique ici ou sur <strong>±</strong> pour basculer en remboursement (négatif).";
    hintContainer.className =
      "flex items-center justify-center gap-1.5 text-xs text-slate-500 mt-2 transition-colors cursor-pointer hover:text-slate-300 select-none";
  }
}
