// Quick Transaction Form Handler
function updateRequiredFields() {
    ['block-expense', 'block-income', 'block-transfer'].forEach(blockId => {
        const block = document.getElementById(blockId);
        if (!block) return;

        const isHidden = block.classList.contains('hidden');
        const fields = block.querySelectorAll('select, input');

        fields.forEach(field => {
            if (isHidden) {
                // On retire le required des blocs masqués pour la validation HTML5
                if (field.hasAttribute('required')) {
                    field.removeAttribute('required');
                    field.setAttribute('data-was-required', 'true');
                }
            } else {
                // On réassocie le required aux champs du bloc actif
                if (field.getAttribute('data-was-required') === 'true') {
                    field.setAttribute('required', 'required');
                    field.removeAttribute('data-was-required');
                }
            }
        });
    });
}

function initQuickTransactionForm() {
    const configEl = document.getElementById('quick-tx-modal-config');
    const isEditMode = configEl ? configEl.dataset.isEdit === 'true' : false;
    const initialTxType = configEl ? configEl.dataset.initialType : 'EXPENSE';

    const displayAmountInput = document.getElementById('total_amount_display');
    const hiddenAmountInput = document.getElementById('total_amount');
    const refundHint = document.getElementById('refund-hint');
    const trWrapper = document.getElementById('meal-voucher-wrapper');
    const trCheckbox = document.getElementById('use_meal_voucher');
    const trDetails = document.getElementById('meal-voucher-details');
    const trAmountInput = document.getElementById('meal_voucher_amount');
    const trAccountSelect = document.getElementById('meal_voucher_account_id');
    const trMaxLabel = document.getElementById('tr-max-label');
    const expenseAccountSelect = document.querySelector('select[name="expense_account"]');
    const categorySelect = document.querySelector('select[name="expense_category"]');
    const trEmptyMsg = document.getElementById('tr-empty-message');

    function autoResizeAmount() {
        if (!displayAmountInput) return;
        const length = displayAmountInput.value.length || 4;
        displayAmountInput.style.width = `${length + 0.5}ch`;
    }

    function getSelectedTrAccount() {
        if (!trAccountSelect || !window.trAccountsInfo || !window.trAccountsInfo.length) return null;
        return window.trAccountsInfo.find(acc => acc.id === trAccountSelect.value);
    }

    function updateTrMax() {
        const trAcc = getSelectedTrAccount();
        if (!trAcc) return;

        if (trMaxLabel) trMaxLabel.textContent = `Max dispo: ${trAcc.remaining.toFixed(2)} €`;

        const total = parseFloat(hiddenAmountInput.value) || 0;
        const suggested = Math.max(0, Math.min(total, trAcc.remaining));
        if (trAmountInput) trAmountInput.value = suggested > 0 ? suggested.toFixed(2) : "";

        if (trAcc.fallback_id && expenseAccountSelect) {
            expenseAccountSelect.value = trAcc.fallback_id;
        }
    }

    function updateTrVisibility() {
        if (!trWrapper || !categorySelect) return;
        const txTypeEl = document.querySelector('input[name="tx_type"]:checked');
        if (!txTypeEl) return;

        const txType = txTypeEl.value;
        const catId = categorySelect.value;
        const isEligible = window.catTrMap && window.catTrMap[catId] === true;
        const hasTrBalance = window.trAccountsInfo && window.trAccountsInfo.some(acc => acc.remaining > 0);

        if (txType === 'EXPENSE' && isEligible) {
            if (hasTrBalance) {
                trWrapper.classList.remove('hidden');
                if (trEmptyMsg) trEmptyMsg.classList.add('hidden');
            } else {
                trWrapper.classList.add('hidden');
                if (trEmptyMsg) trEmptyMsg.classList.remove('hidden');
                if (trCheckbox) {
                    trCheckbox.checked = false;
                    toggleMealVoucherAmount();
                }
            }
        } else {
            trWrapper.classList.add('hidden');
            if (trEmptyMsg) trEmptyMsg.classList.add('hidden');
            if (trCheckbox) {
                trCheckbox.checked = false;
                toggleMealVoucherAmount();
            }
        }
    }

    window.toggleMealVoucherAmount = function() {
        if (!trCheckbox || !trDetails) return;
        if (trCheckbox.checked) {
            trDetails.classList.remove('hidden');
            updateTrMax();
        } else {
            trDetails.classList.add('hidden');
            if (trAmountInput) trAmountInput.value = "";
        }
    };

    window.updateTransferAccounts = function() {
        const sourceSelect = document.querySelector('select[name="source_account"]');
        const destSelect = document.querySelector('select[name="destination_account"]');
        if (!sourceSelect || !destSelect) return;

        const sourceVal = sourceSelect.value;
        const destVal = destSelect.value;

        for (let opt of destSelect.options) {
            opt.disabled = (opt.value !== "" && opt.value === sourceVal);
        }
        for (let opt of sourceSelect.options) {
            opt.disabled = (opt.value !== "" && opt.value === destVal);
        }

        if (sourceSelect.tomselect) sourceSelect.tomselect.sync();
        if (destSelect.tomselect) destSelect.tomselect.sync();
    };

    window.swapTransferAccounts = function(e) {
        if (e && e.preventDefault) e.preventDefault();

        const sourceSelect = document.querySelector('select[name="source_account"]');
        const destSelect = document.querySelector('select[name="destination_account"]');
        if (!sourceSelect || !destSelect) return;

        const tempSourceVal = sourceSelect.value;
        const tempDestVal = destSelect.value;

        Array.from(sourceSelect.options).forEach(opt => opt.disabled = false);
        Array.from(destSelect.options).forEach(opt => opt.disabled = false);

        if (sourceSelect.tomselect) {
            sourceSelect.tomselect.setValue(tempDestVal, true);
        } else {
            sourceSelect.value = tempDestVal;
        }

        if (destSelect.tomselect) {
            destSelect.tomselect.setValue(tempSourceVal, true);
        } else {
            destSelect.value = tempSourceVal;
        }

        sourceSelect.dispatchEvent(new Event('change', { bubbles: true }));
        destSelect.dispatchEvent(new Event('change', { bubbles: true }));

        window.updateTransferAccounts();
    };

    window.toggleTxType = function() {
        const txTypeEl = document.querySelector('input[name="tx_type"]:checked');
        if (!txTypeEl) return;
        const type = txTypeEl.value;

        const blockExpense = document.getElementById('block-expense');
        const blockIncome = document.getElementById('block-income');
        const blockTransfer = document.getElementById('block-transfer');
        const imputationWrapper = document.getElementById('imputation-wrapper');

        if (blockExpense) blockExpense.classList.toggle('hidden', type !== 'EXPENSE');
        if (blockIncome) blockIncome.classList.toggle('hidden', type !== 'INCOME');
        if (blockTransfer) blockTransfer.classList.toggle('hidden', type !== 'TRANSFER');

        if (refundHint) refundHint.classList.toggle('hidden', type !== 'EXPENSE');

        if (imputationWrapper) {
            imputationWrapper.style.opacity = type === 'TRANSFER' ? '0.3' : '1';
            imputationWrapper.style.pointerEvents = type === 'TRANSFER' ? 'none' : 'auto';
        }

        updateTrVisibility();
        updateRequiredFields(); // Mise à jour des attributs 'required' lors du changement d'onglet
    };

    const sourceSelect = document.querySelector('select[name="source_account"]');
    const destSelect = document.querySelector('select[name="destination_account"]');

    if (categorySelect) categorySelect.addEventListener('change', updateTrVisibility);
    if (sourceSelect) sourceSelect.addEventListener('change', window.updateTransferAccounts);
    if (destSelect) destSelect.addEventListener('change', window.updateTransferAccounts);
    if (trAccountSelect) trAccountSelect.addEventListener('change', updateTrMax);

    if (displayAmountInput) {
        displayAmountInput.addEventListener('input', () => {
            autoResizeAmount();
            const val = parseFloat(hiddenAmountInput.value) || 0;
            if (refundHint) {
                if (val < 0) {
                    refundHint.classList.replace("text-slate-500", "text-budget-income");
                    refundHint.classList.add("font-bold");
                } else {
                    refundHint.classList.replace("text-budget-income", "text-slate-500");
                    refundHint.classList.remove("font-bold");
                }
            }
            if (trCheckbox && trCheckbox.checked) {
                updateTrMax();
            }
        });
    }

    // Initialisation
    autoResizeAmount();
    window.updateTransferAccounts();

    if (isEditMode) {
        if (initialTxType) {
            const radioToSelect = document.querySelector(`input[name="tx_type"][value="${initialTxType}"]`);
            if (radioToSelect) radioToSelect.checked = true;
        }
        window.toggleTxType();
        if (trCheckbox && trCheckbox.checked && trDetails) {
            trDetails.classList.remove('hidden');
            const trAcc = getSelectedTrAccount();
            if (trAcc && trMaxLabel) {
                trMaxLabel.textContent = `Max dispo: ${trAcc.remaining.toFixed(2)} €`;
            }
        } else {
            updateTrVisibility();
        }
    } else {
        window.toggleTxType();
    }

    updateRequiredFields(); // Purge initiale des attributs 'required' des onglets masqués
}
