// =========================================================================
// 1. GESTION DES NOTIFICATIONS (TOASTS)
// =========================================================================

// Fonction utilitaire centralisée
function showToast(text, isError = false) {
    const bgColor = isError ? "rgba(244, 63, 94, 0.85)" : "rgba(16, 185, 129, 0.85)";

    Toastify({
        text: text,
        duration: isError ? 3000 : 1500, // On laisse l'erreur un peu plus longtemps
        gravity: "bottom",
        position: "center",
        style: {
            background: bgColor,
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            borderRadius: "9999px",
            padding: "4px 12px",
            fontSize: "0.75rem",
            color: "#020617",
            fontWeight: "600",
            boxShadow: "0 4px 15px -3px rgba(0, 0, 0, 0.3)",
            marginBottom: "4rem"
        }
    }).showToast();
}

document.addEventListener("DOMContentLoaded", () => {
    // =========================================================================
    // 2. AFFICHAGE DES MESSAGES DJANGO
    // =========================================================================
    const messages = document.querySelectorAll("#django-messages > div");
    messages.forEach((msg) => {
        const text = msg.getAttribute("data-message");
        const isError = msg.getAttribute("data-tag") === "error";
        showToast(text, isError);
    });
});

// =========================================================================
// 3. INTERCEPTION DES CONFIRMATIONS HTMX (SWEETALERT2)
// =========================================================================
document.body.addEventListener('htmx:confirm', (evt) => {
    if (!evt.detail.question) return;
    evt.preventDefault();

    Swal.fire({
        title: 'Êtes-vous sûr ?', text: evt.detail.question, icon: 'warning', showCancelButton: true,
        confirmButtonColor: '#f43f5e', cancelButtonColor: '#1e293b', confirmButtonText: 'Oui, continuer', cancelButtonText: 'Annuler',
        background: '#0f172a', color: '#f1f5f9',
        customClass: { popup: 'border border-slate-700 rounded-[1.5rem]', confirmButton: 'font-bold rounded-xl px-5 py-2.5', cancelButton: 'font-bold rounded-xl px-5 py-2.5' }
    }).then((result) => {
        if (result.isConfirmed) evt.detail.issueRequest(true);
    });
});

// =========================================================================
// 4. FORMATAGE ET RESIZE DU CHAMP MONTANT (QUICK TRANSACTION)
// =========================================================================
function formatCurrency(inputEl, hiddenId) {
    let raw = inputEl.value.replace(',', '.').replace(/[^0-9.-]/g, '');
    const hiddenEl = document.getElementById(hiddenId);
    if (hiddenEl) hiddenEl.value = raw;
}

function formatCurrencyOnBlur(inputEl, hiddenId) {
    let hiddenEl = document.getElementById(hiddenId);
    if (!hiddenEl) return;
    let val = parseFloat(hiddenEl.value);
    if (!isNaN(val)) {
        inputEl.value = val.toFixed(2);
    }
}

// Mise à jour automatique des barres de progression
function syncProgressBars() {
    document.querySelectorAll('.progress-bar-fill').forEach((el) => {
        const val = el.getAttribute('data-progress') || '0';
        el.style.setProperty('--progress-val', val);
    });
}

document.addEventListener('DOMContentLoaded', syncProgressBars);
document.body.addEventListener('htmx:afterSettle', syncProgressBars);

// =========================================================================
// 5. TUTORIEL INTERACTIF & SPOTLIGHT OVERLAY
// =========================================================================
function highlightElement(selector, fallbackUrl) {
    const target = document.querySelector(selector);

    // Si l'élément est hors écran ou dans une modale dédiée non présente
    if (!target) {
        if (fallbackUrl) window.location.href = fallbackUrl;
        return;
    }

    // 1. Création de l'overlay sombre s'il n'existe pas
    let overlay = document.getElementById('tour-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'tour-overlay';
        overlay.className = 'fixed inset-0 bg-slate-950/80 z-40 transition-opacity duration-300 pointer-events-auto cursor-pointer';
        overlay.onclick = dismissHighlight;
        document.body.appendChild(overlay);
    }

    // 2. Faire défiler jusqu'à l'élément et appliquer l'effet Spotlight
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });

    target.classList.add('relative', 'z-50', 'ring-4', 'ring-brand', 'ring-offset-4', 'ring-offset-slate-900', 'rounded-xl', 'transition-all');
    target.dataset.spotlight = "true";
}

function dismissHighlight() {
    const overlay = document.getElementById('tour-overlay');
    if (overlay) overlay.remove();

    document.querySelectorAll('[data-spotlight="true"]').forEach((el) => {
        el.classList.remove('relative', 'z-50', 'ring-4', 'ring-brand', 'ring-offset-4', 'ring-offset-slate-900');
        delete el.dataset.spotlight;
    });
}

// =========================================================================
// 6. GESTION DES ERREURS GLOBALES (OFFLINE / 500) VIA HTMX
// =========================================================================
document.body.addEventListener('htmx:sendError', function(event) {
    showToast("Erreur réseau. Vérifiez votre connexion internet.", true);
});

document.body.addEventListener('htmx:responseError', function(event) {
    showToast("Une erreur est survenue sur le serveur. Réessayez plus tard.", true);
});

// =========================================================================
// 7. INITIALISATION TOMSELECT (Sélecteurs dynamiques)
// =========================================================================
function initTomSelects() {
    document.querySelectorAll('select[data-tomselect="true"]').forEach((el) => {
        if (el.tomselect) return; // Évite la double initialisation

        const allowCreate = el.hasAttribute('data-api-create-url');
        const createUrl = el.getAttribute('data-api-create-url');
        const createType = el.getAttribute('data-create-type');

        const hxHeaders = document.body.getAttribute('hx-headers');
        const csrfToken = hxHeaders ? JSON.parse(hxHeaders)['X-CSRFToken'] : '';

        let config = {
            create: false,
            allowEmptyOption: true,
            onDropdownClose: function() {
                this.blur();
            },
            render: {
                no_results: function(data, escape) {
                    return '<div class="no-results p-2 text-sm text-slate-500">Aucun résultat pour "' + escape(data.input) + '"</div>';
                }
            }
        };

        if (allowCreate && createUrl && createType) {
            config.create = function(input, callback) {
                fetch(createUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ type: createType, value: input })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.id) {
                        showToast(`"${data.text}" créé avec succès !`, false);
                        callback({ value: data.id, text: data.text });
                    } else {
                        showToast(data.error || "Erreur lors de la création", true);
                        callback(false);
                    }
                })
                .catch(() => {
                    showToast("Erreur réseau.", true);
                    callback(false);
                });
            };

            config.render.option_create = function(data, escape) {
                return '<div class="create p-2 text-sm font-semibold cursor-pointer text-slate-300">Ajouter <strong class="text-brand">"' + escape(data.input) + '"</strong></div>';
            };
        }

        new TomSelect(el, config);
    });
}

document.addEventListener("DOMContentLoaded", initTomSelects);
document.body.addEventListener('htmx:afterSettle', initTomSelects);

document.addEventListener('focusin', (e) => {
    const target = e.target;
    // On cible uniquement les champs de formulaire
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) {
        // Le délai de 300ms laisse le temps au clavier du téléphone de s'ouvrir
        setTimeout(() => {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 300);
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const floatingBanner = document.getElementById("pwa-install-banner");
    const floatingCloseBtn = document.getElementById("pwa-close-btn");
    const profileCard = document.getElementById("pwa-profile-card");
    const installBtns = document.querySelectorAll(".pwa-install-btn"); // Cible les deux boutons

    let deferredPrompt;

    // 1. DÉTECTION : L'app est-elle déjà installée ?
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

    if (isStandalone) {
        // On supprime purement et simplement les appels à l'installation du DOM
        if (floatingBanner) floatingBanner.remove();
        if (profileCard) profileCard.remove();
        return;
    }

    // 2. GESTION DE LA BANNIÈRE FLOTTANTE
    if (floatingBanner && localStorage.getItem("pwa-prompt-dismissed") !== "true") {
        floatingBanner.classList.remove("hidden");
        setTimeout(() => floatingBanner.classList.remove("translate-y-32", "opacity-0"), 50);
    }

    if (floatingCloseBtn) {
        floatingCloseBtn.addEventListener("click", () => {
            floatingBanner.classList.add("translate-y-32", "opacity-0");
            setTimeout(() => floatingBanner.classList.add("hidden"), 300);
            localStorage.setItem("pwa-prompt-dismissed", "true"); // Masque la bannière flottante, mais la carte profil restera visible !
        });
    }

    // 3. LOGIQUE D'INSTALLATION
    window.addEventListener("beforeinstallprompt", (e) => {
        e.preventDefault();
        deferredPrompt = e;
    });

    const isIos = () => /iphone|ipad|ipod/.test(window.navigator.userAgent.toLowerCase());

    installBtns.forEach(btn => {
        if (isIos()) {
            btn.textContent = "Comment faire ?";
            btn.addEventListener("click", () => {
                Swal.fire({
                    title: 'Installation iOS',
                    html: "<div class='text-left mt-2 space-y-4'><p><b>1.</b> Touchez l'icône <b>Partager</b> en bas de Safari (le carré avec une flèche).</p><p><b>2.</b> Descendez dans le menu et choisissez <b>Sur l'écran d'accueil</b>.</p></div>",
                    icon: 'info',
                    confirmButtonColor: '#10b981',
                    background: '#0f172a',
                    color: '#f1f5f9',
                    customClass: { popup: 'border border-slate-700 rounded-[1.5rem]', confirmButton: 'font-bold rounded-xl px-5 py-2.5' }
                });
            });
        } else {
            btn.addEventListener("click", async () => {
                if (deferredPrompt) {
                    deferredPrompt.prompt();
                    const { outcome } = await deferredPrompt.userChoice;
                    if (outcome === 'accepted') {
                        if (floatingBanner) floatingBanner.remove();
                        if (profileCard) profileCard.remove();
                    }
                    deferredPrompt = null;
                } else {
                    showToast("L'installation automatique n'est pas disponible sur ce navigateur. Utilisez le menu de votre navigateur pour l'ajouter à l'écran d'accueil.", true);
                }
            });
        }
    });
});
