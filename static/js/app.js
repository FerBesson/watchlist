document.addEventListener('alpine:init', () => {
    Alpine.data('stockApp', () => ({
        // Auth State
        isLoggedIn: false,
        isGuest: false,
        showLoginModal: false,
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
        showImportModal: false,
        showTxHelpModal: false,
        portfolioBenchmarkRange: 'ALL',
        portfolioBenchmarkChartInstance: null,
        portfolioBenchmarkLabels: [],
        portfolioBenchmarkSummary: { portfolio_return: 0.0, benchmark_return: 0.0, alpha: 0.0 },
        isBenchmarkLoading: false,
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

                // Precarga en segundo plano de cartera para apertura instantánea
                setTimeout(() => {
                    this.fetchPortfolio();
                    this.fetchTransactions();
                }, 150);
            }
            this.isLoading = false;

            // Watch for changes in date or currency to update exchange rate and ratio
            this.$watch('txForm.date', () => {
                if (this.isLoggedIn || this.isGuest) {
                    this.fetchExchangeRate();
                    this.fetchCedearRatio();
                }
            });
            this.$watch('txForm.currency', () => {
                if (this.isLoggedIn || this.isGuest) {
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
                        this.isGuest = false;
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

        enterAsGuest() {
            this.isGuest = true;
            this.showLoginModal = false;
            
            // Set default guest sample watchlist if empty
            if (!this.watchlists || this.watchlists.length === 0) {
                const defaultWl = {
                    id: 1,
                    name: 'Favoritas',
                    description: 'Lista de seguimiento de prueba (Modo Invitado)',
                    metrics: 'sector,price,prev_close,change_percent',
                    items: [
                        { id: 1, symbol: 'CARTERA', name: null, sector: null, is_divider: true, order: 0, notes: null },
                        { id: 2, symbol: 'AAPL', name: 'Apple Inc.', sector: 'Consumer Electronics', is_divider: false, order: 1, notes: null },
                        { id: 3, symbol: 'MSFT', name: 'Microsoft Corporation', sector: 'Software - Infrastructure', is_divider: false, order: 2, notes: null },
                        { id: 4, symbol: 'TSLA', name: 'Tesla, Inc.', sector: 'Auto Manufacturers', is_divider: false, order: 3, notes: null },
                        { id: 5, symbol: 'CRIPTO', name: null, sector: null, is_divider: true, order: 4, notes: null },
                        { id: 6, symbol: 'BTC-USD', name: 'Bitcoin USD', sector: 'Cryptocurrency', is_divider: false, order: 5, notes: null }
                    ]
                };
                this.watchlists = [defaultWl];
            }
            
            if (this.watchlists.length > 0) {
                this.selectWatchlist(this.watchlists[0].id);
            }
            this.fetchExchangeRate();
        },

        openLoginModal() {
            this.showLoginModal = true;
            this.$nextTick(() => this.initGoogleSignIn());
        },

        closeLoginModal() {
            this.showLoginModal = false;
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
                this.isGuest = false;
                this.showLoginModal = false;

                // Cargar datos del usuario desde la base de datos
                await this.fetchWatchlists();
                if (this.watchlists.length > 0) {
                    this.selectWatchlist(this.watchlists[0].id);
                }
                await this.fetchExchangeRate();

                // Precarga en segundo plano de cartera
                setTimeout(() => {
                    this.fetchPortfolio();
                    this.fetchTransactions();
                }, 150);

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
            try {
                this.stopAutoRefresh();
            } catch (e) {
                console.warn('Error stopping auto refresh:', e);
            }
            try {
                this.stopPortfolioRefresh();
            } catch (e) {
                console.warn('Error stopping portfolio refresh:', e);
            }

            try {
                localStorage.removeItem('auth_token');
                sessionStorage.clear();
            } catch (e) {}

            this.authToken = null;
            this.currentUser = null;
            this.isLoggedIn = false;
            this.isGuest = false;
            this.showLoginModal = false;
            this.currentWatchlistId = null;
            this.currentWatchlist = null;
            this.selectedStock = null;
            this.watchlists = [];
            this.watchlistItems = [];
            this.portfolioItems = [];
            this.transactions = [];
            this.closedTrades = [];

            if (window.google && window.google.accounts && window.google.accounts.id) {
                try {
                    window.google.accounts.id.disableAutoSelect();
                } catch (e) {
                    console.warn('[Google Auth] disableAutoSelect error:', e);
                }
            }

            this.$nextTick(() => this.initGoogleSignIn());
        },

        stopPortfolioAutoRefresh() {
            this.stopPortfolioRefresh();
        },


        // Fetch all watchlists
        async fetchWatchlists() {
            if (this.isGuest) {
                return;
            }
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
                
                // CARGA INSTANTÁNEA (OPTIMISTIC UI): Mostrar los activos de la memoria inmediatamente ordenados
                if (this.currentWatchlist.items && this.currentWatchlist.items.length > 0) {
                    // Mantener cotizaciones previas si ya existían en memoria
                    const existingMap = new Map(this.watchlistItems.map(it => [it.symbol, it]));
                    const sortedItems = [...this.currentWatchlist.items].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id - b.id);
                    
                    this.watchlistItems = sortedItems.map(it => {
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
                let newItems = [];
                if (this.isGuest) {
                    if (!this.currentWatchlist) return;
                    const items = (this.currentWatchlist.items || []).sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id - b.id);
                    const stockSymbols = items.filter(it => !it.is_divider).map(it => it.symbol);
                    
                    let quotesMap = {};
                    if (stockSymbols.length > 0) {
                        try {
                            const qRes = await fetch(`/api/quotes?symbols=${encodeURIComponent(stockSymbols.join(','))}`);
                            if (qRes.ok) {
                                quotesMap = await qRes.json();
                            }
                        } catch (qErr) {
                            console.error('Error fetching guest quotes:', qErr);
                        }
                    }
                    
                    newItems = items.map(it => {
                        if (it.is_divider) {
                            return {
                                id: it.id,
                                symbol: it.symbol,
                                name: null,
                                sector: null,
                                notes: it.notes,
                                is_divider: true,
                                order: it.order,
                                price: null,
                                prev_close: null,
                                change: null,
                                change_percent: null,
                                volume: null,
                                market_cap: null,
                                pe: null,
                                dividend_yield: null
                            };
                        }
                        const q = quotesMap[it.symbol] || {};
                        return {
                            id: it.id,
                            symbol: it.symbol,
                            name: it.name || q.name || it.symbol,
                            sector: it.sector || q.sector || "International",
                            notes: it.notes,
                            is_divider: false,
                            order: it.order,
                            price: q.price !== undefined ? q.price : null,
                            prev_close: q.prev_close !== undefined ? q.prev_close : null,
                            change: q.change !== undefined ? q.change : null,
                            change_percent: q.change_percent !== undefined ? q.change_percent : null,
                            volume: q.volume !== undefined ? q.volume : null,
                            market_cap: q.market_cap !== undefined ? q.market_cap : null,
                            pe: q.pe !== undefined ? q.pe : null,
                            dividend_yield: q.dividend_yield !== undefined ? q.dividend_yield : null
                        };
                    });
                } else {
                    const response = await this.authFetch(`/api/watchlists/${this.currentWatchlistId}/quotes`);
                    if (response.ok) {
                        newItems = await response.json();
                    }
                }
                
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
                if (!this.portfolioItems || this.portfolioItems.length === 0) {
                    this.isPortfolioLoading = true;
                }
                this.startPortfolioRefresh();
                
                // Actualizar en segundo plano sin congelar la vista
                Promise.all([this.fetchPortfolio(), this.fetchTransactions()]).finally(() => {
                    this.isPortfolioLoading = false;
                });
            }
        },

        // Fetch consolidated portfolio data
        async fetchPortfolio() {
            if (this.isGuest) {
                const symbols = Array.from(new Set(this.transactions.filter(t => t.symbol && t.symbol !== 'CASH').map(t => t.symbol)));
                let quotesMap = {};
                if (symbols.length > 0) {
                    try {
                        const qRes = await fetch(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`);
                        if (qRes.ok) quotesMap = await qRes.json();
                    } catch (e) {
                        console.error('Error fetching quotes for guest portfolio:', e);
                    }
                }
                
                const holdingsMap = {};
                let realizedPnL = 0;
                let winningTrades = 0;
                let losingTrades = 0;
                let totalWinAmount = 0;
                let totalLossAmount = 0;
                let largestWin = 0;
                let largestLoss = 0;
                
                const sortedTxs = [...this.transactions].sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0));
                
                sortedTxs.forEach(tx => {
                    const sym = (tx.symbol || '').toUpperCase();
                    if (!sym || sym === 'CASH') return;
                    
                    if (!holdingsMap[sym]) {
                        holdingsMap[sym] = {
                            symbol: sym,
                            vn_total: 0,
                            acciones_equivalentes: 0,
                            costo_total_usd: 0,
                            ppc_comparable: 0,
                            precio_afuera: null,
                            valor_actual_usd: 0,
                            pnl_usd: 0,
                            pnl_percent: 0,
                            prev_close: null
                        };
                    }
                    
                    const item = holdingsMap[sym];
                    const cantAcciones = tx.quantity / (tx.ratio || 1.0);
                    const costUsd = cantAcciones * (tx.price_comparable || (tx.price * tx.ratio * tx.exchange_rate));
                    
                    if (tx.operation_type === 'BUY') {
                        item.vn_total += tx.quantity;
                        item.acciones_equivalentes += cantAcciones;
                        item.costo_total_usd += costUsd;
                        item.ppc_comparable = item.acciones_equivalentes > 0 ? (item.costo_total_usd / item.acciones_equivalentes) : 0;
                    } else if (tx.operation_type === 'SELL') {
                        if (item.acciones_equivalentes > 0) {
                            const avgCost = item.costo_total_usd / item.acciones_equivalentes;
                            const sellQty = Math.min(cantAcciones, item.acciones_equivalentes);
                            const saleGain = (tx.price_comparable - avgCost) * sellQty;
                            realizedPnL += saleGain;
                            
                            if (saleGain > 0) {
                                winningTrades++;
                                totalWinAmount += saleGain;
                                if (saleGain > largestWin) largestWin = saleGain;
                            } else if (saleGain < 0) {
                                losingTrades++;
                                totalLossAmount += Math.abs(saleGain);
                                if (Math.abs(saleGain) > largestLoss) largestLoss = Math.abs(saleGain);
                            }
                            
                            item.acciones_equivalentes = Math.max(0, item.acciones_equivalentes - sellQty);
                            item.vn_total = Math.max(0, item.vn_total - tx.quantity);
                            item.costo_total_usd = item.acciones_equivalentes * avgCost;
                        }
                    }
                });
                
                const activeItems = Object.values(holdingsMap).filter(h => h.acciones_equivalentes > 0.0001);
                activeItems.forEach(h => {
                    const q = quotesMap[h.symbol] || {};
                    h.precio_afuera = q.price !== undefined ? q.price : null;
                    h.prev_close = q.prev_close !== undefined ? q.prev_close : null;
                    if (h.precio_afuera !== null) {
                        h.valor_actual_usd = h.acciones_equivalentes * h.precio_afuera;
                        h.pnl_usd = h.valor_actual_usd - h.costo_total_usd;
                        h.pnl_percent = h.costo_total_usd > 0 ? (h.pnl_usd / h.costo_total_usd * 100) : 0;
                    } else {
                        h.valor_actual_usd = h.costo_total_usd;
                        h.pnl_usd = 0;
                        h.pnl_percent = 0;
                    }
                });
                
                this.portfolioItems = activeItems;
                this.portfolioRealizedPnL = realizedPnL;
                
                const totalTrades = winningTrades + losingTrades;
                this.portfolioMetrics = {
                    total_trades: totalTrades,
                    winning_trades: winningTrades,
                    losing_trades: losingTrades,
                    win_rate: totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0.0,
                    profit_factor: totalLossAmount > 0 ? (totalWinAmount / totalLossAmount) : (totalWinAmount > 0 ? 99.0 : 1.0),
                    avg_win: winningTrades > 0 ? (totalWinAmount / winningTrades) : 0.0,
                    avg_loss: losingTrades > 0 ? (totalLossAmount / losingTrades) : 0.0,
                    win_loss_ratio: (losingTrades > 0 && winningTrades > 0) ? ((totalWinAmount / winningTrades) / (totalLossAmount / losingTrades)) : 0.0,
                    largest_win: largestWin,
                    largest_loss: largestLoss
                };
                
                this.$nextTick(() => {
                    this.renderPortfolioTreemap();
                    this.fetchPortfolioBenchmarkChart();
                });
                return;
            }
            
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
                        this.fetchPortfolioBenchmarkChart();
                    });
                }
            } catch (error) {
                console.error('Error fetching portfolio:', error);
            }
        },

        // Cambiar rango de tiempo del benchmark (1M, 3M, 6M, 1A, TODO)
        setPortfolioBenchmarkRange(r) {
            this.portfolioBenchmarkRange = r;
            this.fetchPortfolioBenchmarkChart(r);
        },

        // Obtener datos históricos de rendimiento comparativo (Cartera vs S&P 500)
        async fetchPortfolioBenchmarkChart(range = null) {
            const timeRange = range || this.portfolioBenchmarkRange || 'ALL';
            this.isBenchmarkLoading = true;

            try {
                let response;
                if (this.isGuest) {
                    response = await fetch(`/api/portfolio/benchmark-chart?range=${encodeURIComponent(timeRange)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            transactions: this.transactions,
                            range: timeRange
                        })
                    });
                } else {
                    response = await this.authFetch(`/api/portfolio/benchmark-chart?range=${encodeURIComponent(timeRange)}`);
                }

                if (response && response.ok) {
                    const data = await response.json();
                    this.portfolioBenchmarkLabels = data.labels || [];
                    this.portfolioBenchmarkSummary = data.summary || { portfolio_return: 0.0, benchmark_return: 0.0, alpha: 0.0 };
                    this.$nextTick(() => {
                        this.renderPortfolioBenchmarkChart(data);
                    });
                } else {
                    console.warn('Failed to load benchmark chart data');
                    this.portfolioBenchmarkLabels = [];
                    this.renderPortfolioBenchmarkChart({ labels: [], portfolio_returns: [], benchmark_returns: [] });
                }
            } catch (error) {
                console.error('Error loading benchmark chart data:', error);
                this.portfolioBenchmarkLabels = [];
            } finally {
                this.isBenchmarkLoading = false;
            }
        },

        // Renderizar gráfico interactivo de líneas con Chart.js
        renderPortfolioBenchmarkChart(data) {
            const ctx = document.getElementById('portfolioBenchmarkChart');
            if (!ctx) return;

            if (this.portfolioBenchmarkChartInstance) {
                this.portfolioBenchmarkChartInstance.destroy();
                this.portfolioBenchmarkChartInstance = null;
            }

            if (!data || !data.labels || data.labels.length === 0) {
                return;
            }

            // Formatear etiquetas de fecha limpias para el eje X
            const formattedLabels = data.labels.map(dStr => {
                try {
                    const parts = dStr.split('-');
                    if (parts.length === 3) {
                        return `${parts[2]}/${parts[1]}`;
                    }
                    return dStr;
                } catch (e) {
                    return dStr;
                }
            });

            // Gradiente Neón Cian para la Cartera
            const chartContext = ctx.getContext('2d');
            const portGradient = chartContext.createLinearGradient(0, 0, 0, 180);
            portGradient.addColorStop(0, 'rgba(0, 240, 255, 0.22)');
            portGradient.addColorStop(1, 'rgba(0, 240, 255, 0.0)');

            this.portfolioBenchmarkChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: formattedLabels,
                    datasets: [
                        {
                            label: 'Cartera',
                            data: data.portfolio_returns,
                            borderColor: '#00f0ff',
                            backgroundColor: portGradient,
                            fill: true,
                            tension: 0.25,
                            borderWidth: 2,
                            pointRadius: data.labels.length > 50 ? 0 : 2,
                            pointHoverRadius: 4,
                            pointBackgroundColor: '#00f0ff'
                        },
                        {
                            label: 'S&P 500',
                            data: data.benchmark_returns,
                            borderColor: '#a855f7',
                            backgroundColor: 'transparent',
                            fill: false,
                            tension: 0.25,
                            borderWidth: 1.5,
                            borderDash: [4, 4],
                            pointRadius: data.labels.length > 50 ? 0 : 2,
                            pointHoverRadius: 4,
                            pointBackgroundColor: '#a855f7'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        duration: 350
                    },
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: '#121212',
                            titleColor: '#a3a3a3',
                            bodyColor: '#f5f5f5',
                            borderColor: '#262626',
                            borderWidth: 1,
                            padding: 8,
                            displayColors: true,
                            titleFont: { family: 'monospace', size: 10 },
                            bodyFont: { family: 'monospace', size: 11, weight: 'bold' },
                            callbacks: {
                                title: (tooltipItems) => {
                                    const idx = tooltipItems[0].dataIndex;
                                    return data.labels[idx] || tooltipItems[0].label;
                                },
                                label: (context) => {
                                    const val = context.parsed.y;
                                    const sign = val >= 0 ? '+' : '';
                                    return ` ${context.dataset.label}: ${sign}${val.toFixed(2)}%`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                display: true,
                                color: 'rgba(255, 255, 255, 0.04)',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#525252',
                                font: { family: 'monospace', size: 9 },
                                maxTicksLimit: 5,
                                maxRotation: 0
                            }
                        },
                        y: {
                            grid: {
                                display: true,
                                color: (context) => context.tick && context.tick.value === 0 ? 'rgba(255, 255, 255, 0.15)' : 'rgba(255, 255, 255, 0.04)',
                                drawBorder: false
                            },
                            ticks: {
                                color: '#737373',
                                font: { family: 'monospace', size: 9 },
                                callback: (val) => `${val >= 0 ? '+' : ''}${val}%`
                            }
                        }
                    }
                }
            });
        },

        // Fetch transactions log
        async fetchTransactions() {
            if (this.isGuest) {
                return;
            }
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

            if (this.isGuest) {
                const txData = {
                    id: isEditing ? this.editingTransactionId : Date.now(),
                    symbol: payload.symbol,
                    operation_type: payload.operation_type,
                    quantity: payload.quantity,
                    price: payload.price,
                    currency: payload.currency,
                    ratio: payload.ratio,
                    exchange_rate: payload.exchange_rate,
                    price_comparable: payload.price * payload.ratio * payload.exchange_rate,
                    date: payload.date || new Date().toISOString(),
                    notes: payload.notes
                };
                
                if (isEditing) {
                    const idx = this.transactions.findIndex(t => t.id === this.editingTransactionId);
                    if (idx !== -1) this.transactions[idx] = txData;
                } else {
                    this.transactions.unshift(txData);
                }
                
                this.editingTransactionId = null;
                this.txForm.symbol = '';
                this.txForm.quantity = '';
                this.txForm.price = '';
                this.txForm.date = '';
                this.txForm.notes = '';
                
                await this.fetchPortfolio();
                return;
            }

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
            if (this.isGuest) {
                this.transactions = this.transactions.filter(t => t.id !== id);
                await this.fetchPortfolio();
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

            // Close modal
            this.showImportModal = false;

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
            if (this.isGuest) {
                this.transactions = [];
                await this.fetchPortfolio();
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
            
            if (this.isGuest) {
                const newId = Date.now();
                const newWl = {
                    id: newId,
                    name: name,
                    description: '',
                    metrics: metricsStr,
                    items: []
                };
                this.watchlists.push(newWl);
                this.selectWatchlist(newId);
                return;
            }
            
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
            
            if (this.isGuest) {
                const wl = this.watchlists.find(w => w.id === id);
                if (wl) {
                    wl.name = name;
                    if (this.currentWatchlistId === id && this.currentWatchlist) {
                        this.currentWatchlist.name = name;
                    }
                }
                return;
            }
            
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
                    if (this.currentWatchlistId === id && this.currentWatchlist) {
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
            
            if (this.isGuest) {
                this.watchlists = this.watchlists.filter(w => w.id !== id);
                this.currentWatchlistId = null;
                this.currentWatchlist = null;
                this.watchlistItems = [];
                this.selectedStock = null;
                this.stopAutoRefresh();
                if (this.watchlists.length > 0) {
                    this.selectWatchlist(this.watchlists[0].id);
                }
                return;
            }
            
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
            
            const metricsStr = this.selectedMetrics.join(',');
            if (this.currentWatchlist) {
                this.currentWatchlist.metrics = metricsStr;
            }
            
            if (this.isGuest) {
                return;
            }
            
            // Save metrics to current watchlist in DB
            if (this.currentWatchlistId) {
                try {
                    await this.authFetch(`/api/watchlists/${this.currentWatchlistId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            metrics: metricsStr
                        })
                    });
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
            if (!this.currentWatchlistId || !this.currentWatchlist) return;
            const sym = symbol.trim().toUpperCase();
            
            if (this.isGuest) {
                if (!this.currentWatchlist.items) this.currentWatchlist.items = [];
                const existing = this.currentWatchlist.items.find(i => !i.is_divider && i.symbol.toUpperCase() === sym);
                if (existing) {
                    alert(`El símbolo ${sym} ya está en esta lista.`);
                    return;
                }
                
                this.isLoading = true;
                try {
                    let stockName = sym;
                    let stockSector = 'International';
                    const qRes = await fetch(`/api/quotes?symbols=${encodeURIComponent(sym)}`);
                    if (qRes.ok) {
                        const qData = await qRes.json();
                        if (qData[sym]) {
                            stockName = qData[sym].name || sym;
                            stockSector = qData[sym].sector || 'International';
                        }
                    }
                    
                    const maxOrder = this.currentWatchlist.items.length > 0 
                        ? Math.max(...this.currentWatchlist.items.map(i => i.order ?? 0)) + 1 
                        : 0;
                    
                    const newItem = {
                        id: Date.now(),
                        symbol: sym,
                        name: stockName,
                        sector: stockSector,
                        is_divider: false,
                        order: maxOrder,
                        notes: null
                    };
                    this.currentWatchlist.items.push(newItem);
                    this.searchQuery = '';
                    this.searchResults = [];
                    await this.fetchWatchlistQuotes();
                } catch (e) {
                    console.error('Error adding stock in guest mode:', e);
                } finally {
                    this.isLoading = false;
                }
                return;
            }
            
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
            if (!this.currentWatchlistId || !this.currentWatchlist) return;
            if (!confirm(`¿Remover ${symbol} de esta lista?`)) return;
            
            if (this.isGuest) {
                if (this.currentWatchlist.items) {
                    this.currentWatchlist.items = this.currentWatchlist.items.filter(i => i.symbol !== symbol);
                }
                if (this.selectedStock && this.selectedStock.symbol === symbol) {
                    this.selectedStock = null;
                }
                await this.fetchWatchlistQuotes();
                return;
            }
            
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
            if (!this.currentWatchlistId || !this.currentWatchlist || !this.newSectionName.trim()) return;
            const name = this.newSectionName.trim();
            this.newSectionName = '';
            
            if (this.isGuest) {
                if (!this.currentWatchlist.items) this.currentWatchlist.items = [];
                const maxOrder = this.currentWatchlist.items.length > 0 
                    ? Math.max(...this.currentWatchlist.items.map(i => i.order ?? 0)) + 1 
                    : 0;
                const newDivider = {
                    id: Date.now(),
                    symbol: name,
                    name: null,
                    sector: null,
                    is_divider: true,
                    order: maxOrder,
                    notes: null
                };
                this.currentWatchlist.items.push(newDivider);
                await this.fetchWatchlistQuotes();
                return;
            }
            
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
            if (this.isGuest) {
                if (this.currentWatchlist && this.currentWatchlist.items) {
                    const items = this.currentWatchlist.items;
                    const idx = items.findIndex(it => it.id === itemId);
                    if (idx !== -1) {
                        if (direction === 'up' && idx > 0) {
                            const temp = items[idx];
                            items[idx] = items[idx - 1];
                            items[idx - 1] = temp;
                        } else if (direction === 'down' && idx < items.length - 1) {
                            const temp = items[idx];
                            items[idx] = items[idx + 1];
                            items[idx + 1] = temp;
                        }
                        items.forEach((it, i) => it.order = i);
                        await this.fetchWatchlistQuotes();
                    }
                }
                return;
            }
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
                        
                        if (this.isGuest) {
                            if (this.currentWatchlist && this.currentWatchlist.items) {
                                const itemMap = new Map(this.currentWatchlist.items.map(it => [it.id, it]));
                                this.currentWatchlist.items = itemIds.map((id, idx) => {
                                    const it = itemMap.get(id);
                                    if (it) it.order = idx;
                                    return it;
                                }).filter(Boolean);
                            }
                            await this.fetchWatchlistQuotes();
                            return;
                        }

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
            
            if (this.isGuest) {
                if (this.currentWatchlist && this.currentWatchlist.items) {
                    const div = this.currentWatchlist.items.find(i => i.id === id);
                    if (div) {
                        div.symbol = name;
                    }
                }
                await this.fetchWatchlistQuotes();
                return;
            }
            
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
                        
                        if (this.isGuest) {
                            const wlMap = new Map(this.watchlists.map(w => [w.id, w]));
                            this.watchlists = wlIds.map((id, idx) => {
                                const w = wlMap.get(id);
                                if (w) w.order = idx;
                                return w;
                            }).filter(Boolean);
                            return;
                        }

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
                    glowColor = 'rgba(0, 255, 102, 0.2)';
                } else if (this.selectedStock.change_percent < 0) {
                    themeColor = '#ff3b30'; // Neon Red
                    glowColor = 'rgba(255, 59, 48, 0.15)';
                }
            }

            // Create gradient
            const gradient = ctx.getContext('2d').createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, glowColor);
            gradient.addColorStop(1, 'rgba(18, 18, 18, 0)');

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
                            backgroundColor: '#121214',
                            titleColor: '#737373',
                            bodyColor: '#e5e5e5',
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
                                color: '#262626',
                                drawTicks: false
                            },
                            ticks: {
                                color: '#737373',
                                font: { family: 'Fira Code', size: 9 },
                                maxTicksLimit: 8
                            }
                        },
                        y: {
                            grid: {
                                color: '#262626',
                                drawTicks: false
                            },
                            ticks: {
                                color: '#737373',
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
                    colors: ['#121214'] // Match card background
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
                        let pnlClass = 'text-neutral-400';
                        if (point.rawSymbol !== 'CASH' && point.pnl !== null) {
                            const sign = point.pnl >= 0 ? '+' : '';
                            pnlText = `${sign}${point.pnl.toFixed(2)}%`;
                            pnlClass = point.pnl >= 0 ? 'text-[#00ff66]' : 'text-[#ff3b30]';
                        } else if (point.rawSymbol === 'CASH') {
                            pnlText = 'Neutral';
                            pnlClass = 'text-neutral-400';
                        }
                        
                        return `
                            <div class="p-3 bg-[#121214] border border-neutral-800 font-mono text-[11px] text-left" style="border-radius: 4px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5);">
                                <div class="font-bold text-[#00f0ff] mb-1.5">&gt; ${point.rawSymbol}</div>
                                <div class="mb-1 text-neutral-300">Valor: <span class="text-white font-bold">$${valStr}</span></div>
                                <div class="mb-1 text-neutral-300">Rendimiento: <span class="${pnlClass} font-bold">${pnlText}</span></div>
                                <div class="text-neutral-400 text-[10px]">Nominal: ${point.qty.toLocaleString()}</div>
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
                return 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%23d92672" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="22"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>';
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
