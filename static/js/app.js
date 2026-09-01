document.addEventListener('alpine:init', () => {
    Alpine.data('stockApp', () => ({
        // Auth State
        isLoggedIn: false,
        authChecking: true,
        currentUser: null,
        authToken: localStorage.getItem('auth_token') || null,
        hasGoogleClientId: false,
        googleClientId: null,
        // State
        watchlists: [],
        currentWatchlistId: null,
        currentWatchlist: null,
        watchlistItems: [],
        isLoading: false,
        isQuotesLoading: false,
        
        // Portfolio & Transaction State
        activeView: 'watchlists', // 'watchlists' or 'portfolio'
        portfolioItems: [],
        portfolioRealizedPnL: 0.0,
        portfolioRealizedPnLPercent: 0.0,
        portfolioMetrics: {
            total_trades: 0,
            winning_trades: 0,
            losing_trades: 0,
            win_rate: 0.0,
            profit_factor: 1.0,
            avg_win: 0.0,
            avg_loss: 0.0,
            win_loss_ratio: 0.0,
            largest_win: 0.0,
            largest_loss: 0.0
        },
        closedTrades: [],
        portfolioTIR: null,
        transactions: [],
        isPortfolioLoading: false,
        txForm: {
            symbol: '',
            operation_type: 'BUY',
            quantity: '',
            price: '',
            currency: 'ARS',
            ratio: 1.0,
            exchange_input: 1300,
            date: '',
            notes: ''
        },
        portfolioRefreshIntervalId: null,
        portfolioSearchResults: [],
        portfolioSearchTimeout: null,
        editingTransactionId: null,
        isImporting: false,
        // Inline Creation State
        isCreatingWatchlist: false,
        newWatchlistInputName: '',
        
        // Inline Rename State
        editingWatchlistId: null,
        editingWatchlistName: '',
        
        // Inline Divider Rename State
        editingDividerId: null,
        editingDividerName: '',
        
        // Search & Sections
        searchQuery: '',
        newSectionName: '',
        searchResults: [],
        searchTimeout: null,
        isSearching: false,

        // Detail & Charts
        selectedStock: null,
        chartRange: '1mo',
        chartInstance: null,
        portfolioTreemapInstance: null,
        sortableInstance: null,
        watchlistSortableInstance: null,
        
        // Refresh Timer
        refreshIntervalId: null,
        lastUpdated: null,

        // Available metrics for customization
        availableMetrics: [
            { id: 'sector', label: 'Sector' },
            { id: 'price', label: 'Precio Actual' },
            { id: 'prev_close', label: 'Cierre Anterior' },
            { id: 'change', label: 'Var. Diaria ($)' },
            { id: 'change_percent', label: 'Var. Diaria (%)' },
            { id: 'volume', label: 'Volumen' },
            { id: 'market_cap', label: 'Cap. Mercado' },
            { id: 'pe', label: 'Ratio P/E' },
            { id: 'dividend_yield', label: 'Dividendo (%)' }
        ],
        selectedMetrics: ['sector', 'price', 'prev_close', 'change_percent'],

        // Init App
        async init() {
            this.isLoading = true;
            await this.checkAuthStatus();

            if (this.isLoggedIn) {
                await this.fetchWatchlists();
                await this.fetchExchangeRate();
            }
            this.isLoading = false;

            // Watch for changes in date or currency to update exchange rate and ratio
            this.$watch('txForm.date', () => {
                if (this.isLoggedIn) {
                    this.fetchExchangeRate();
                    this.fetchCedearRatio();
                }
            });
            this.$watch('txForm.currency', () => {
                if (this.isLoggedIn) {
                    this.fetchExchangeRate();
                }
            });
        },
        // --- AUTHENTICATION METHODS ---
        async authFetch(url, options = {}) {
            options.headers = options.headers || {};
            if (this.authToken) {
                if (options.headers instanceof Headers) {
                    options.headers.set('Authorization', `Bearer ${this.authToken}`);
                } else {
                    options.headers['Authorization'] = `Bearer ${this.authToken}`;
                }
            }
            const response = await fetch(url, options);
            if (response.status === 401 && this.isLoggedIn) {
                console.warn('[Auth] Sesión expirada o token inválido.');
                this.logout();
            }
            return response;
        },

        async checkAuthStatus() {
            this.authChecking = true;
            try {
                // 1. Obtener configuración pública (Google Client ID)
                const configRes = await fetch('/api/auth/config');
                if (configRes.ok) {
                    const cfg = await configRes.json();
                    if (cfg.google_client_id) {
                        this.googleClientId = cfg.google_client_id;
                        this.hasGoogleClientId = true;
                    }
                }

                // 2. Verificar token actual si existe
                if (this.authToken) {
                    const meRes = await this.authFetch('/api/auth/me');
                    if (meRes.ok) {
                        this.currentUser = await meRes.json();
                        this.isLoggedIn = true;
                    } else {
                        this.authToken = null;
                        localStorage.removeItem('auth_token');
                        this.isLoggedIn = false;
                    }
                }
            } catch (e) {
                console.error('[Auth] Error verificando estado de auth:', e);
            } finally {
                this.authChecking = false;
                if (!this.isLoggedIn) {
                    this.$nextTick(() => this.initGoogleSignIn());
                }
            }
        },

        initGoogleSignIn() {
            if (!this.googleClientId) {
                console.warn('[Google Auth] GOOGLE_CLIENT_ID no configurado en el backend (.env).');
                return;
            }

            const checkGis = () => {
                if (window.google && window.google.accounts && window.google.accounts.id) {
                    window.google.accounts.id.initialize({
                        client_id: this.googleClientId,
                        callback: (res) => this.handleGoogleCredential(res)
                    });

                    const btnContainer = document.getElementById('google-signin-btn-container');
                    if (btnContainer) {
                        btnContainer.innerHTML = '';
                        window.google.accounts.id.renderButton(btnContainer, {
                            theme: 'filled_black',
                            size: 'large',
                            shape: 'rectangular',
                            text: 'signin_with',
                            logo_alignment: 'left',
                            width: 280
                        });
                    }
                } else {
                    setTimeout(checkGis, 200);
                }
            };
            checkGis();
        },

        async handleGoogleCredential(response) {
            try {
                this.isLoading = true;
                const res = await fetch('/api/auth/google', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: response.credential })
                });

                if (!res.ok) {
                    const err = await res.json();
                    alert('Error de inicio de sesión: ' + (err.detail || 'No se pudo verificar'));
                    return;
                }

                const data = await res.json();
                this.authToken = data.access_token;
                localStorage.setItem('auth_token', data.access_token);
                this.currentUser = data.user;
                this.isLoggedIn = true;

                // Cargar datos del usuario
                await this.fetchWatchlists();
                await this.fetchExchangeRate();

                if (this.activeView === 'portfolio') {
                    await this.fetchPortfolio();
                    await this.fetchTransactions();
                }
            } catch (e) {
                console.error('Error al iniciar sesión:', e);
                alert('Error al conectar con el servidor para iniciar sesión');
            } finally {
                this.isLoading = false;
            }
        },

        logout() {
            this.stopAutoRefresh();
            this.stopPortfolioAutoRefresh();
            localStorage.removeItem('auth_token');
            this.authToken = null;
            this.currentUser = null;
            this.isLoggedIn = false;
            this.watchlists = [];
            this.watchlistItems = [];
            this.portfolioItems = [];
            this.transactions = [];
            this.closedTrades = [];
            this.$nextTick(() => this.initGoogleSignIn());
        },


        // Fetch all watchlists
        async fetchWatchlists() {
            try {
                const response = await this.authFetch('/api/watchlists');
                if (response.ok) {
                    this.watchlists = await response.json();
                }
            } catch (error) {
                console.error('Error fetching watchlists:', error);
            }
        },

        // Select a watchlist and load its items
        async selectWatchlist(id) {
            this.stopAutoRefresh();
            this.currentWatchlistId = id;
            this.selectedStock = null;
            
            // Find in current list
            this.currentWatchlist = this.watchlists.find(w => w.id === id);
            
            if (this.currentWatchlist) {
                // Read metrics saved in DB
                if (this.currentWatchlist.metrics) {
                    this.selectedMetrics = this.currentWatchlist.metrics.split(',').map(m => m.trim());
                } else {
                    this.selectedMetrics = ['sector', 'price', 'prev_close', 'change_percent'];
                }
                
                // CARGA INSTANTÁNEA (OPTIMISTIC UI): Mostrar los activos de la memoria inmediatamente
                if (this.currentWatchlist.items && this.currentWatchlist.items.length > 0) {
                    // Mantener cotizaciones previas si ya existían en memoria
                    const existingMap = new Map(this.watchlistItems.map(it => [it.symbol, it]));
                    this.watchlistItems = this.currentWatchlist.items.map(it => {
                        const prev = existingMap.get(it.symbol);
                        return {
                            ...it,
                            price: prev ? prev.price : null,
                            prev_close: prev ? prev.prev_close : null,
                            change: prev ? prev.change : null,
                            change_percent: prev ? prev.change_percent : null,
                            volume: prev ? prev.volume : null,
                            market_cap: prev ? prev.market_cap : null,
                            pe: prev ? prev.pe : null,
                            dividend_yield: prev ? prev.dividend_yield : null
                        };
                    });
                }
                
                // Cargar cotizaciones actualizadas en background
                this.isQuotesLoading = true;
                await this.fetchWatchlistQuotes();
                this.isQuotesLoading = false;
                
                // Start refresh loop
                this.startAutoRefresh();
            }
        },


        // Fetch quotes for current watchlist
        async fetchWatchlistQuotes() {
            if (!this.currentWatchlistId) return;
            this.isQuotesLoading = true;
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/quotes`);
                if (response.ok) {
                    const newItems = await response.json();
                    
                    // Compare with old prices to set flash animations
                    newItems.forEach(newItem => {
                        const oldItem = this.watchlistItems.find(item => item.symbol === newItem.symbol);
                        if (oldItem && oldItem.price !== undefined && newItem.price !== undefined) {
                            if (newItem.price > oldItem.price) {
                                newItem.flash = 'up';
                            } else if (newItem.price < oldItem.price) {
                                newItem.flash = 'down';
                            } else if (oldItem.flash) {
                                // Persist existing flash if price hasn't changed again before timeout
                                newItem.flash = oldItem.flash;
                            }
                        }
                    });
                    
                    this.watchlistItems = newItems;
                    this.lastUpdated = new Date().toLocaleTimeString();
                    
                    // Clear flashes after 1.5 seconds
                    setTimeout(() => {
                        this.watchlistItems.forEach(item => {
                            if (item.flash) {
                                item.flash = null;
                            }
                        });
                    }, 1500);
                    
                    // If we have a selected stock, update its details
                    if (this.selectedStock) {
                        const updated = this.watchlistItems.find(item => item.symbol === this.selectedStock.symbol);
                        if (updated) {
                            this.selectedStock = updated;
                        }
                    }
                }
            } catch (error) {
                console.error('Error fetching watchlist quotes:', error);
            } finally {
                this.isQuotesLoading = false;
            }
        },

        // Start 10 seconds auto-refresh
        startAutoRefresh() {
            this.refreshIntervalId = setInterval(() => {
                this.fetchWatchlistQuotes();
            }, 10000);
        },

        // Stop auto-refresh
        stopAutoRefresh() {
            if (this.refreshIntervalId) {
                clearInterval(this.refreshIntervalId);
                this.refreshIntervalId = null;
            }
        },

        // Select active view (watchlists or portfolio)
        async selectView(view) {
            this.activeView = view;
            if (view === 'watchlists') {
                this.stopPortfolioRefresh();
                if (this.currentWatchlistId) {
                    this.startAutoRefresh();
                }
            } else if (view === 'portfolio') {
                this.stopAutoRefresh();
                this.selectedStock = null;
                this.isPortfolioLoading = true;
                await Promise.all([this.fetchPortfolio(), this.fetchTransactions()]);
                this.isPortfolioLoading = false;
                this.startPortfolioRefresh();
            }
        },

        // Fetch consolidated portfolio data
        async fetchPortfolio() {
            try {
                const response = await this.authFetch('/api/portfolio');
                if (response.ok) {
                    const data = await response.json();
                    this.portfolioItems = data.items;
                    this.portfolioRealizedPnL = data.realized_pnl;
                    this.portfolioRealizedPnLPercent = data.realized_pnl_percent;
                    if (data.metrics) this.portfolioMetrics = data.metrics;
                    if (data.closed_trades) this.closedTrades = data.closed_trades;
                    this.portfolioTIR = data.tir;
                    this.$nextTick(() => {
                        this.renderPortfolioTreemap();
                    });
                }
            } catch (error) {
                console.error('Error fetching portfolio:', error);
            }
        },

        // Fetch transactions log
        async fetchTransactions() {
            try {
                const response = await this.authFetch('/api/transactions');
                if (response.ok) {
                    this.transactions = await response.json();
                }
            } catch (error) {
                console.error('Error fetching transactions:', error);
            }
        },

        // Submit or update transaction
        async submitTransaction() {
            if (!this.txForm.symbol || !this.txForm.quantity || !this.txForm.price || !this.txForm.ratio || !this.txForm.exchange_input) {
                alert('Por favor complete todos los campos obligatorios.');
                return;
            }

            let qty = parseFloat(this.txForm.quantity);
            let prc = parseFloat(this.txForm.price);
            let rat = parseFloat(this.txForm.ratio);
            let exInput = parseFloat(this.txForm.exchange_input);
            let exRate = 1.0;

            if (this.txForm.currency === 'ARS') {
                exRate = 1.0 / exInput;
            } else if (this.txForm.currency === 'USD') {
                // If user entered e.g. 4 for 4%, convert to 0.04.
                // If they entered 0.04 directly, keep as 0.04.
                let canje = exInput;
                if (canje >= 1.0) {
                    canje = canje / 100.0;
                }
                exRate = 1.0 - canje;
            }

            const payload = {
                symbol: this.txForm.symbol.trim().toUpperCase(),
                operation_type: this.txForm.operation_type,
                quantity: qty,
                price: prc,
                currency: this.txForm.currency,
                ratio: rat,
                exchange_rate: exRate,
                date: this.txForm.date ? new Date(this.txForm.date).toISOString() : null,
                notes: this.txForm.notes.trim() || null
            };

            const isEditing = this.editingTransactionId !== null;
            const url = isEditing ? `/api/transactions/${this.editingTransactionId}` : '/api/transactions';
            const method = isEditing ? 'PUT' : 'POST';

            try {
                const response = await this.authFetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    // Reset editing state
                    this.editingTransactionId = null;
                    
                    // Clear form but keep ratio and exchange defaults for convenience
                    this.txForm.symbol = '';
                    this.txForm.quantity = '';
                    this.txForm.price = '';
                    this.txForm.date = '';
                    this.txForm.notes = '';
                    
                    // Reload data
                    await Promise.all([this.fetchPortfolio(), this.fetchTransactions()]);
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo guardar la operación'}`);
                }
            } catch (error) {
                console.error('Error submitting transaction:', error);
            }
        },

        // Start editing a transaction
        editTransaction(tx) {
            console.log("Editing transaction:", tx);
            this.editingTransactionId = tx.id;
            this.txForm.symbol = tx.symbol || '';
            this.txForm.operation_type = tx.operation_type || 'BUY';
            this.txForm.quantity = tx.quantity || '';
            this.txForm.price = tx.price || '';
            this.txForm.currency = tx.currency || 'ARS';
            this.txForm.ratio = tx.ratio || 1.0;
            
            if (tx.currency === 'ARS') {
                this.txForm.exchange_input = tx.exchange_rate ? (1.0 / tx.exchange_rate).toFixed(2) : 1.0;
            } else {
                this.txForm.exchange_input = tx.exchange_rate ? ((1.0 - tx.exchange_rate) * 100.0).toFixed(2) : 0.0;
            }
            
            if (tx.date) {
                if (typeof tx.date === 'string' && tx.date.match(/^\d{4}-\d{2}-\d{2}/)) {
                    this.txForm.date = tx.date.substring(0, 10);
                } else {
                    try {
                        const parsedDate = new Date(tx.date);
                        if (!isNaN(parsedDate.getTime())) {
                            this.txForm.date = parsedDate.toISOString().split('T')[0];
                        } else {
                            this.txForm.date = '';
                        }
                    } catch (e) {
                        console.error('Error parsing date:', e);
                        this.txForm.date = '';
                    }
                }
            } else {
                this.txForm.date = '';
            }
            
            this.txForm.notes = tx.notes || '';
            
            console.log("Form values loaded:", JSON.parse(JSON.stringify(this.txForm)));
            
            // Scroll to form smoothly
            const formElem = document.querySelector('form');
            if (formElem) {
                formElem.scrollIntoView({ behavior: 'smooth' });
            }
        },

        // Cancel editing a transaction
        cancelEditTransaction() {
            this.editingTransactionId = null;
            this.txForm.symbol = '';
            this.txForm.quantity = '';
            this.txForm.price = '';
            this.txForm.date = '';
            this.txForm.notes = '';
            this.txForm.ratio = 1.0;
            this.fetchExchangeRate();
        },

        // Delete a transaction from log
        async deleteTransaction(id) {
            if (!confirm('¿Está seguro de eliminar esta transacción? Esta acción recalculará el PPC.')) {
                return;
            }
            try {
                const response = await this.authFetch(`/api/transactions/${id}`, {
                    method: 'DELETE'
                });
                if (response.ok) {
                    await Promise.all([this.fetchPortfolio(), this.fetchTransactions()]);
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo eliminar la operación'}`);
                }
            } catch (error) {
                console.error('Error deleting transaction:', error);
            }
        },

        // Import transactions from an Excel file
        async importExcel(event) {
            const file = event.target.files[0];
            if (!file) return;

            // Reset input value so it triggers change event if same file is selected again
            event.target.value = '';

            const formData = new FormData();
            formData.append('file', file);

            this.isImporting = true;
            try {
                const response = await this.authFetch('/api/transactions/import', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const result = await response.json();
                    alert(`Importación completada:\n- Creadas: ${result.imported}\n- Duplicadas (omitidas): ${result.skipped}`);
                    // Reload data
                    await Promise.all([this.fetchPortfolio(), this.fetchTransactions()]);
                } else {
                    const err = await response.json();
                    alert(`Error de importación: ${err.detail || 'No se pudo procesar el archivo Excel'}`);
                }
            } catch (error) {
                console.error('Error importing Excel:', error);
                alert('Error al intentar subir o procesar el archivo Excel.');
            } finally {
                this.isImporting = false;
            }
        },

        // Delete all transactions from log
        async deleteAllTransactions() {
            if (!confirm('¿Está absolutamente seguro de eliminar TODAS las transacciones registradas? Esta acción es irreversible y vaciará tu cartera.')) {
                return;
            }
            try {
                const response = await this.authFetch('/api/transactions', {
                    method: 'DELETE'
                });
                if (response.ok) {
                    const result = await response.json();
                    alert(`Éxito: Se han eliminado las ${result.count} transacciones.`);
                    await Promise.all([this.fetchPortfolio(), this.fetchTransactions()]);
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudieron eliminar las operaciones'}`);
                }
            } catch (error) {
                console.error('Error deleting all transactions:', error);
                alert('Error al intentar eliminar las transacciones.');
            }
        },

        // Auto refresh for portfolio holdings
        startPortfolioRefresh() {
            this.stopPortfolioRefresh();
            this.portfolioRefreshIntervalId = setInterval(() => {
                this.fetchPortfolio();
            }, 10000);
        },

        // Stop portfolio refresh
        stopPortfolioRefresh() {
            if (this.portfolioRefreshIntervalId) {
                clearInterval(this.portfolioRefreshIntervalId);
                this.portfolioRefreshIntervalId = null;
            }
        },

        // Start inline watchlist creation
        startCreatingWatchlist() {
            this.isCreatingWatchlist = true;
            this.newWatchlistInputName = '';
            this.$nextTick(() => {
                const el = document.getElementById('new-watchlist-input');
                if (el) el.focus();
            });
        },

        // Confirm inline watchlist creation
        async confirmCreateWatchlist() {
            if (!this.isCreatingWatchlist) return;
            
            const name = this.newWatchlistInputName.trim();
            this.isCreatingWatchlist = false; // Reset first to prevent duplicate triggers (blur and enter)
            
            if (!name) return; // Cancel if empty
            
            const metricsStr = this.selectedMetrics.join(',');
            try {
                const response = await this.authFetch('/api/watchlists', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        description: '',
                        metrics: metricsStr
                    })
                });

                if (response.ok) {
                    const data = await response.json();
                    await this.fetchWatchlists();
                    // Select the newly created watchlist
                    this.selectWatchlist(data.id);
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo crear la lista'}`);
                }
            } catch (error) {
                console.error('Error creating watchlist:', error);
            }
        },

        // Start inline watchlist renaming
        startEditingWatchlist(wl) {
            this.editingWatchlistId = wl.id;
            this.editingWatchlistName = wl.name;
            this.$nextTick(() => {
                const el = document.getElementById('edit-watchlist-input');
                if (el) el.focus();
            });
        },

        // Confirm inline watchlist renaming
        async confirmEditWatchlist(id) {
            if (this.editingWatchlistId !== id) return;
            
            const name = this.editingWatchlistName.trim();
            this.editingWatchlistId = null; // Reset first to prevent double trigger (enter + blur)
            
            if (!name) return; // Cancel if empty
            
            try {
                const response = await this.authFetch(`/api/watchlists/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name
                    })
                });

                if (response.ok) {
                    await this.fetchWatchlists();
                    // Update currentWatchlist title if this is the active one
                    if (this.currentWatchlistId === id) {
                        this.currentWatchlist.name = name;
                    }
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo renombrar la lista'}`);
                }
            } catch (error) {
                console.error('Error renaming watchlist:', error);
            }
        },

        // Delete current watchlist
        async deleteWatchlist(id) {
            if (!confirm('¿Estás seguro de eliminar esta lista de seguimiento?')) return;
            
            try {
                const response = await this.authFetch(`/api/watchlists/${id}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    this.currentWatchlistId = null;
                    this.currentWatchlist = null;
                    this.watchlistItems = [];
                    this.selectedStock = null;
                    this.stopAutoRefresh();
                    
                    await this.fetchWatchlists();
                    if (this.watchlists.length > 0) {
                        this.selectWatchlist(this.watchlists[0].id);
                    }
                }
            } catch (error) {
                console.error('Error deleting watchlist:', error);
            }
        },

        // Toggle metric visibility and save to DB
        async toggleMetric(metricId) {
            if (this.selectedMetrics.includes(metricId)) {
                // Keep at least symbol + one metric
                if (this.selectedMetrics.length > 1) {
                    this.selectedMetrics = this.selectedMetrics.filter(m => m !== metricId);
                }
            } else {
                this.selectedMetrics.push(metricId);
            }
            
            // Save metrics to current watchlist in DB
            if (this.currentWatchlistId) {
                const metricsStr = this.selectedMetrics.join(',');
                try {
                    await this.authFetch(`/api/watchlists/${this.currentWatchlistId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            metrics: metricsStr
                        })
                    });
                    // Refresh watchlist metadata cache
                    if (this.currentWatchlist) {
                        this.currentWatchlist.metrics = metricsStr;
                    }
                    this.fetchWatchlists();
                } catch (error) {
                    console.error('Error updating watchlist metrics:', error);
                }
            }
        },

        // Check if a metric is active
        isMetricActive(metricId) {
            return this.selectedMetrics.includes(metricId);
        },

        // Autocomplete Search for Stocks
        searchStocks() {
            if (this.searchTimeout) clearTimeout(this.searchTimeout);
            if (!this.searchQuery.trim()) {
                this.searchResults = [];
                return;
            }

            this.isSearching = true;
            this.searchTimeout = setTimeout(async () => {
                try {
                    const response = await this.authFetch(`/api/search?q=${encodeURIComponent(this.searchQuery.trim())}`);
                    if (response.ok) {
                        this.searchResults = await response.json();
                    }
                } catch (error) {
                    console.error('Search error:', error);
                } finally {
                    this.isSearching = false;
                }
            }, 300); // 300ms debounce
        },

        // Autocomplete Search for Portfolio Transactions
        searchPortfolioStocks() {
            if (this.portfolioSearchTimeout) clearTimeout(this.portfolioSearchTimeout);
            const term = this.txForm.symbol.trim().toUpperCase();
            if (!term) {
                this.portfolioSearchResults = [];
                return;
            }

            if (term === "CASH") {
                this.portfolioSearchResults = [];
                this.txForm.price = 1.0;
                this.txForm.ratio = 1.0;
                this.fetchExchangeRate();
                return;
            }

            this.portfolioSearchTimeout = setTimeout(async () => {
                try {
                    const response = await this.authFetch(`/api/search?q=${encodeURIComponent(this.txForm.symbol.trim())}`);
                    if (response.ok) {
                        this.portfolioSearchResults = await response.json();
                    }
                } catch (error) {
                    console.error('Portfolio search error:', error);
                }
            }, 300); // 300ms debounce
        },

        // Select a stock from search results for transaction form
        async selectPortfolioStock(symbol) {
            this.txForm.symbol = symbol;
            this.portfolioSearchResults = [];
            
            if (symbol.toUpperCase() === "CASH") {
                this.txForm.price = 1.0;
                this.txForm.ratio = 1.0;
                this.fetchExchangeRate();
                return;
            }
            
            try {
                const dateStr = this.txForm.date || '';
                const response = await this.authFetch(`/api/cedear-info/${symbol}?date=${encodeURIComponent(dateStr)}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data && data.ratio) {
                        this.txForm.ratio = data.ratio;
                    }
                    if (data && data.symbol_origin) {
                        this.txForm.symbol = data.symbol_origin;
                    }
                }
            } catch (error) {
                console.error('Error fetching Cedear info:', error);
            }
        },

        // Fetch automated exchange rate from backend
        async fetchExchangeRate() {
            const dateStr = this.txForm.date || '';
            const currency = this.txForm.currency || 'ARS';
            // Debounce or validate incomplete date string if user typing manually
            if (dateStr && dateStr.length < 10) return;
            
            try {
                const response = await this.authFetch(`/api/exchange-rate?date=${encodeURIComponent(dateStr)}&currency=${encodeURIComponent(currency)}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data && data.exchange_rate_input !== undefined) {
                        this.txForm.exchange_input = data.exchange_rate_input;
                    }
                }
            } catch (error) {
                console.error('Error fetching exchange rate:', error);
            }
        },

        // Fetch automated Cedear ratio from backend
        async fetchCedearRatio() {
            const symbol = this.txForm.symbol || '';
            const dateStr = this.txForm.date || '';
            if (!symbol || symbol.toUpperCase() === "CASH") return;
            if (dateStr && dateStr.length < 10) return;
            
            try {
                const response = await this.authFetch(`/api/cedear-info/${encodeURIComponent(symbol)}?date=${encodeURIComponent(dateStr)}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data && data.ratio !== undefined) {
                        this.txForm.ratio = data.ratio;
                    }
                }
            } catch (error) {
                console.error('Error fetching Cedear ratio:', error);
            }
        },

        // Auto-configure exchange rate for cash transactions on currency changes
        onCurrencyChange() {
            if (this.txForm.symbol.trim().toUpperCase() === "CASH") {
                this.fetchExchangeRate();
            }
        },

        // Add a stock from search results to current watchlist
        async addStock(symbol) {
            if (!this.currentWatchlistId) return;
            this.isLoading = true;
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: symbol })
                });

                if (response.ok) {
                    this.searchQuery = '';
                    this.searchResults = [];
                    await this.fetchWatchlistQuotes();
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo añadir el símbolo'}`);
                }
            } catch (error) {
                console.error('Error adding stock:', error);
            } finally {
                this.isLoading = false;
            }
        },

        // Remove stock from current watchlist
        async removeStock(symbol) {
            if (!this.currentWatchlistId) return;
            if (!confirm(`¿Remover ${symbol} de esta lista?`)) return;
            
            this.isLoading = true;
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/items/${symbol}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    if (this.selectedStock && this.selectedStock.symbol === symbol) {
                        this.selectedStock = null;
                    }
                    await this.fetchWatchlistQuotes();
                }
            } catch (error) {
                console.error('Error removing stock:', error);
            } finally {
                this.isLoading = false;
            }
        },

        // Add a section divider (TradingView-style)
        async addSection() {
            if (!this.currentWatchlistId || !this.newSectionName.trim()) return;
            const name = this.newSectionName.trim();
            this.newSectionName = '';
            
            this.isLoading = true;
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/items`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: name,
                        is_divider: true
                    })
                });

                if (response.ok) {
                    await this.fetchWatchlistQuotes();
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo crear la sección'}`);
                }
            } catch (error) {
                console.error('Error adding section:', error);
            } finally {
                this.isLoading = false;
            }
        },

        // Move an item (stock or divider) up or down in sorting order
        async moveItem(itemId, direction) {
            if (!this.currentWatchlistId) return;
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/items/${itemId}/move?direction=${direction}`, {
                    method: 'POST'
                });
                if (response.ok) {
                    await this.fetchWatchlistQuotes();
                }
            } catch (error) {
                console.error(`Error moving item ${direction}:`, error);
            }
        },

        // Initialize SortableJS on the table body for drag and drop reordering
        initSortable() {
            this.$nextTick(() => {
                const el = document.getElementById('watchlist-table-body');
                if (!el) return;
                
                // Destroy existing instance if active
                if (this.sortableInstance) {
                    this.sortableInstance.destroy();
                    this.sortableInstance = null;
                }
                
                this.sortableInstance = Sortable.create(el, {
                    animation: 150,
                    handle: '.drag-handle', // Drag handle selector
                    ghostClass: 'bg-slate-800/80',
                    onStart: () => {
                        this.stopAutoRefresh(); // Pause background refresh while dragging
                    },
                    onEnd: async (evt) => {
                        this.startAutoRefresh(); // Resume background refresh
                        
                        // If index didn't change, do nothing
                        if (evt.oldIndex === evt.newIndex) return;

                        // Get all row elements to retrieve new order of IDs
                        const rows = el.querySelectorAll('tr[data-id]');
                        const itemIds = Array.from(rows).map(row => parseInt(row.getAttribute('data-id')));
                        
                        try {
                            const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/reorder`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(itemIds)
                            });
                            
                            if (response.ok) {
                                // Sync local array with new database order
                                await this.fetchWatchlistQuotes();
                            } else {
                                console.error('Failed to save new order in database.');
                            }
                        } catch (error) {
                            console.error('Error reordering items:', error);
                        }
                    }
                });
            });
        },

        // Start inline divider renaming
        startEditingDivider(item) {
            this.editingDividerId = item.id;
            this.editingDividerName = item.symbol;
            this.$nextTick(() => {
                const el = document.getElementById('edit-divider-input');
                if (el) el.focus();
            });
        },

        // Confirm inline divider renaming
        async confirmEditDivider(id) {
            if (this.editingDividerId !== id) return;
            
            const name = this.editingDividerName.trim();
            this.editingDividerId = null; // Reset first to prevent double trigger (enter + blur)
            
            if (!name) return; // Cancel if empty
            
            try {
                const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/items/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: name
                    })
                });

                if (response.ok) {
                    await this.fetchWatchlistQuotes();
                } else {
                    const err = await response.json();
                    alert(`Error: ${err.detail || 'No se pudo renombrar la sección'}`);
                }
            } catch (error) {
                console.error('Error renaming divider:', error);
            }
        },

        // Initialize SortableJS on the sidebar watchlist nav for reordering
        initWatchlistSortable() {
            this.$nextTick(() => {
                const el = document.getElementById('watchlist-nav');
                if (!el) return;
                
                // Destroy existing instance if active
                if (this.watchlistSortableInstance) {
                    this.watchlistSortableInstance.destroy();
                    this.watchlistSortableInstance = null;
                }
                
                this.watchlistSortableInstance = Sortable.create(el, {
                    animation: 150,
                    handle: '.wl-drag-handle', // Drag handle selector
                    ghostClass: 'bg-slate-800/80',
                    onEnd: async (evt) => {
                        // If index didn't change, do nothing
                        if (evt.oldIndex === evt.newIndex) return;

                        // Get all watchlist row elements to retrieve new order of IDs
                        const rows = el.querySelectorAll('[data-wl-id]');
                        const wlIds = Array.from(rows).map(row => parseInt(row.getAttribute('data-wl-id')));
                        
                        try {
                            const response = await this.authFetch('/api/watchlists/reorder', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(wlIds)
                            });
                            
                            if (response.ok) {
                                // Sync local array with new database order
                                await this.fetchWatchlists();
                            } else {
                                console.error('Failed to save new watchlist order in database.');
                            }
                        } catch (error) {
                            console.error('Error reordering watchlists:', error);
                        }
                    }
                });
            });
        },

        // Show Stock details and plot history chart
        viewStockDetail(stock) {
            this.selectedStock = stock;
            this.chartRange = '1mo'; // reset range
            this.$nextTick(() => {
                this.fetchChartData();
            });
        },

        // Fetch and plot historical chart
        async fetchChartData() {
            if (!this.selectedStock) return;
            
            const symbol = this.selectedStock.symbol;
            const range = this.chartRange;
            
            try {
                const response = await this.authFetch(`/api/charts/${symbol}?range=${range}`);
                if (response.ok) {
                    const data = await response.json();
                    this.renderChart(data);
                } else {
                    console.warn('Failed to load chart data');
                    // Draw empty or handle error
                    this.renderChart([]);
                }
            } catch (error) {
                console.error('Error loading chart data:', error);
            }
        },

        // Render Chart.js
        renderChart(chartData) {
            const ctx = document.getElementById('tickerChart');
            if (!ctx) return;
            
            if (this.chartInstance) {
                this.chartInstance.destroy();
            }

            if (!chartData || chartData.length === 0) {
                // If no data, show message inside canvas or clear
                this.chartInstance = new Chart(ctx, {
                    type: 'line',
                    data: { labels: [], datasets: [] },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false },
                            title: { display: true, text: 'SIN DATOS DISPONIBLES', color: '#ff3b30', font: { family: 'Fira Code' } }
                        },
                        scales: {
                            x: { display: false },
                            y: { display: false }
                        }
                    }
                });
                return;
            }

            // Extract labels and values
            const labels = chartData.map(d => {
                const date = new Date(d.time * 1000);
                if (this.chartRange === '1d') {
                    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                }
                return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
            });
            const values = chartData.map(d => d.value);

            // Neon color theme depending on stock direction or cyan
            let themeColor = '#00f0ff'; // Neon Cyan
            let glowColor = 'rgba(0, 240, 255, 0.15)';
            
            if (this.selectedStock && this.selectedStock.change_percent !== null) {
                if (this.selectedStock.change_percent > 0) {
                    themeColor = '#00ff66'; // Neon Green
                    glowColor = 'rgba(0, 255, 102, 0.15)';
                } else if (this.selectedStock.change_percent < 0) {
                    themeColor = '#ff3b30'; // Neon Red
                    glowColor = 'rgba(255, 59, 48, 0.15)';
                }
            }

            // Create gradient
            const gradient = ctx.getContext('2d').createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, glowColor);
            gradient.addColorStop(1, 'rgba(13, 18, 28, 0)');

            this.chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Precio',
                        data: values,
                        borderColor: themeColor,
                        borderWidth: 2,
                        backgroundColor: gradient,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointHoverBackgroundColor: themeColor,
                        pointHoverBorderColor: '#fff',
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            enabled: true,
                            backgroundColor: '#0d121c',
                            titleColor: '#64748b',
                            bodyColor: '#cbd5e1',
                            borderColor: themeColor,
                            borderWidth: 1,
                            titleFont: { family: 'Fira Code', size: 11 },
                            bodyFont: { family: 'Fira Code', size: 12 },
                            callbacks: {
                                label: function(context) {
                                    return ` Precio: $${context.parsed.y.toFixed(2)}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: '#1e293b',
                                drawTicks: false
                            },
                            ticks: {
                                color: '#64748b',
                                font: { family: 'Fira Code', size: 9 },
                                maxTicksLimit: 8
                            }
                        },
                        y: {
                            grid: {
                                color: '#1e293b',
                                drawTicks: false
                            },
                            ticks: {
                                color: '#64748b',
                                font: { family: 'Fira Code', size: 9 },
                                callback: function(value) {
                                    return '$' + value.toFixed(2);
                                }
                            }
                        }
                    }
                }
            });
        },

        // Render Portfolio distribution Treemap (Heatmap)
        renderPortfolioTreemap() {
            const container = document.getElementById('portfolioTreemap');
            if (!container) return;

            // Destroy previous instance if it exists
            if (this.portfolioTreemapInstance) {
                this.portfolioTreemapInstance.destroy();
                this.portfolioTreemapInstance = null;
            }

            // Filter items with valid value and compute total
            const items = this.portfolioItems.filter(item => item.valor_actual_usd && item.valor_actual_usd !== 0);
            
            if (items.length === 0) {
                container.innerHTML = `<div class="text-slate-500 font-mono text-xs text-center py-12">[ SIN POSICIONES ACTIVAS ]</div>`;
                return;
            }
            
            // Calculate total for percentage calculation
            const totalValue = items.reduce((acc, item) => acc + Math.abs(item.valor_actual_usd), 0);

            // Prepare series data for ApexCharts Treemap
            const data = items.map(item => {
                const val = Math.abs(item.valor_actual_usd);
                const pct = ((val / totalValue) * 100).toFixed(1);
                
                // Color mapping based on unrealized P&L percent
                let color = '#475569'; // Slate-600 (neutral/CASH)
                if (item.symbol !== 'CASH' && item.pnl_percent !== null) {
                    if (item.pnl_percent > 5.0) {
                        color = '#10b981'; // emerald-500 (bright green)
                    } else if (item.pnl_percent > 0.0) {
                        color = '#047857'; // emerald-700 (dark green)
                    } else if (item.pnl_percent < -5.0) {
                        color = '#ef4444'; // red-500 (bright red)
                    } else if (item.pnl_percent < 0.0) {
                        color = '#b91c1c'; // red-700 (dark red)
                    }
                }
                
                return {
                    x: `${item.symbol} (${pct}%)`,
                    y: val,
                    fillColor: color,
                    pnl: item.pnl_percent,
                    pnlUsd: item.pnl_usd,
                    rawSymbol: item.symbol,
                    qty: item.acciones_equivalentes
                };
            });

            // Sort data descending by value
            data.sort((a, b) => b.y - a.y);

            const options = {
                series: [{
                    data: data
                }],
                legend: {
                    show: false
                },
                chart: {
                    height: '100%',
                    type: 'treemap',
                    toolbar: {
                        show: false
                    },
                    background: 'transparent'
                },
                stroke: {
                    show: true,
                    width: 1.5,
                    colors: ['#0d121c'] // Match card background
                },
                title: {
                    show: false
                },
                plotOptions: {
                    treemap: {
                        enableShades: false,
                        distributed: true,
                        useFillColorAsStroke: false
                    }
                },
                dataLabels: {
                    enabled: true,
                    style: {
                        fontSize: '11px',
                        fontFamily: 'Fira Code, monospace',
                        fontWeight: 'bold',
                        colors: ['#ffffff']
                    },
                    formatter: function(text, op) {
                        return text;
                    },
                    offsetY: -2
                },
                tooltip: {
                    enabled: true,
                    theme: 'dark',
                    custom: function({ series, seriesIndex, dataPointIndex, w }) {
                        const point = w.config.series[seriesIndex].data[dataPointIndex];
                        const valStr = point.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                        
                        let pnlText = '0.00%';
                        let pnlClass = 'text-slate-400';
                        if (point.rawSymbol !== 'CASH' && point.pnl !== null) {
                            const sign = point.pnl >= 0 ? '+' : '';
                            pnlText = `${sign}${point.pnl.toFixed(2)}%`;
                            pnlClass = point.pnl >= 0 ? 'text-[#00ff66]' : 'text-[#ff3b30]';
                        } else if (point.rawSymbol === 'CASH') {
                            pnlText = 'Neutral';
                            pnlClass = 'text-slate-400';
                        }
                        
                        return `
                            <div class="p-3 bg-[#0d121c] border border-slate-800 font-mono text-[11px] text-left" style="border-radius: 4px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5);">
                                <div class="font-bold text-[#00f0ff] mb-1.5">&gt; ${point.rawSymbol}</div>
                                <div class="mb-1 text-slate-300">Valor: <span class="text-slate-100 font-bold">$${valStr}</span></div>
                                <div class="mb-1 text-slate-300">Rendimiento: <span class="${pnlClass} font-bold">${pnlText}</span></div>
                                <div class="text-slate-400 text-[10px]">Nominal: ${point.qty.toLocaleString()}</div>
                            </div>
                        `;
                    }
                }
            };

            this.portfolioTreemapInstance = new ApexCharts(container, options);
            this.portfolioTreemapInstance.render();
        },

        // Getters reactivos para totales del portafolio
        get portfolioCost() {
            return this.portfolioItems.reduce((acc, item) => acc + (item.costo_total_usd || 0), 0);
        },

        get portfolioValue() {
            return this.portfolioItems.reduce((acc, item) => {
                if (item.precio_afuera !== null && item.precio_afuera !== undefined) {
                    return acc + (item.acciones_equivalentes * item.precio_afuera);
                }
                return acc + (item.costo_total_usd || 0); // fallback al costo si no hay precio de mercado
            }, 0);
        },

        get portfolioPnL() {
            return this.portfolioValue - this.portfolioCost;
        },

        get portfolioPnLPercent() {
            const cost = this.portfolioCost;
            return cost > 0 ? (this.portfolioPnL / cost * 100) : 0;
        },

        get portfolioDailyChangePercent() {
            let currentVal = 0;
            let prevVal = 0;
            this.portfolioItems.forEach(item => {
                const qty = item.acciones_equivalentes || 0;
                const currentPrice = item.precio_afuera;
                const prevClose = item.prev_close !== null && item.prev_close !== undefined ? item.prev_close : currentPrice;
                
                if (currentPrice !== null && currentPrice !== undefined) {
                    currentVal += qty * currentPrice;
                    prevVal += qty * prevClose;
                } else {
                    const cost = item.costo_total_usd || 0;
                    currentVal += cost;
                    prevVal += cost;
                }
            });
            if (prevVal > 0) {
                return ((currentVal - prevVal) / prevVal) * 100;
            }
            return 0;
        },

        // Helper: formatting large numbers (Market Cap)
        formatMarketCap(value) {
            if (value === null || value === undefined) return 'N/A';
            if (value >= 1e12) return (value / 1e12).toFixed(2) + 'T';
            if (value >= 1e9) return (value / 1e9).toFixed(2) + 'B';
            if (value >= 1e6) return (value / 1e6).toFixed(2) + 'M';
            return value.toLocaleString();
        },

        // Helper: format percent
        formatPercent(value) {
            if (value === null || value === undefined) return '0.00%';
            const sign = value > 0 ? '+' : '';
            return `${sign}${value.toFixed(2)}%`;
        },
        
        // Helper: format float/price
        formatPrice(value) {
            if (value === null || value === undefined) return 'N/A';
            return `$${value.toFixed(2)}`;
        },

        // Helper: Get logo URL for stock/crypto symbol
        getLogoUrl(symbol) {
            if (!symbol) return '';
            if (symbol.toUpperCase() === 'CASH') {
                return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%2300ff66" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="22"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>';
            }
            let clean = symbol.toUpperCase().split('.')[0].split('-')[0]; // e.g. BTC-USD -> BTC, AAPL.BA -> AAPL
            return `https://assets.parqet.com/logos/symbol/${clean}`;
        },

        // Helper: Handle logo image load error by showing fallback initials
        handleLogoError(event, symbol) {
            const img = event.target;
            const parent = img.parentElement;
            if (img && parent) {
                img.style.display = 'none';
                let initials = '?';
                if (symbol) {
                    let upper = symbol.toUpperCase();
                    if (upper === 'CASH') {
                        initials = '$';
                    } else {
                        let clean = upper.replace(/[^A-Z0-9]/g, '');
                        initials = clean.substring(0, 2);
                    }
                }
                let fallbackSpan = parent.querySelector('.logo-initials');
                if (!fallbackSpan) {
                    fallbackSpan = document.createElement('span');
                    fallbackSpan.className = 'logo-initials';
                    parent.appendChild(fallbackSpan);
                }
                fallbackSpan.innerText = initials;
                fallbackSpan.style.display = 'inline-block';
            }
        },

        // Helper: Deterministic color for fallback badge background
        getSymbolColor(symbol) {
            if (!symbol) return '#1e293b';
            if (symbol.toUpperCase() === 'CASH') return '#042f1a';
            let hash = 0;
            for (let i = 0; i < symbol.length; i++) {
                hash = symbol.charCodeAt(i) + ((hash << 5) - hash);
            }
            const colors = ['#1e3a8a', '#065f46', '#7c2d12', '#4c1d95', '#831843', '#1e293b', '#312e81', '#064e3b'];
            return colors[Math.abs(hash) % colors.length];
        }
    }));
});
