"""
Correlation Network — Kripto Varlık Korelasyon Ağ Analizi

NetworkX ile kripto varlıklar arasındaki fiyat korelasyonlarını
çizge (graph) olarak modelleyerek bulaşma riski tespiti yapar.
"""
import time
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from utils.logger import logger

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    NX_AVAILABLE = False
    logger.debug("networkx yuklu degil, korelasyon agı devre disi")


class CorrelationNetwork:
    """
    Kripto varlıklar arası korelasyon ağı.
    
    Kullanım:
        cn = CorrelationNetwork()
        cn.update_network(["BTC", "ETH", "SOL", ...])
        risk = cn.detect_contagion_risk("BTC")
        diversification = cn.find_diversification()
    """

    COINGECKO_URL = "https://api.coingecko.com/api/v3"
    
    # CoinGecko ID mapping
    COIN_IDS = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "XRP": "ripple", "DOGE": "dogecoin", "SHIB": "shiba-inu",
        "PEPE": "pepe", "LINK": "chainlink", "AVAX": "avalanche-2",
        "ADA": "cardano", "DOT": "polkadot", "LTC": "litecoin",
        "UNI": "uniswap", "AAVE": "aave", "BONK": "bonk",
    }

    def __init__(self):
        self.graph = None
        self.correlation_matrix = None
        self.price_data = {}
        self.last_update = None
        self.cache_duration = 1800  # 30 dakika
        
        if NX_AVAILABLE:
            self.graph = nx.Graph()
            logger.info("Korelasyon Agi baslatildi (NetworkX)")
        else:
            logger.info("Korelasyon Agi devre disi (networkx yok)")

    def update_network(self, coins: List[str] = None) -> bool:
        """
        Korelasyon ağını güncelle (son 30 gün verisiyle).
        """
        if not NX_AVAILABLE:
            return False
            
        # Cache kontrolü
        if self.last_update:
            elapsed = (datetime.now() - self.last_update).total_seconds()
            if elapsed < self.cache_duration:
                return True

        if coins is None:
            coins = list(self.COIN_IDS.keys())

        try:
            # Fiyat verilerini çek
            self._fetch_price_data(coins)
            
            if len(self.price_data) < 3:
                logger.debug("Yeterli fiyat verisi yok, ag guncellenmedi")
                return False
            
            # Korelasyon matrisi hesapla
            self._calculate_correlations()
            
            # Ağı oluştur
            self._build_graph()
            
            self.last_update = datetime.now()
            logger.info(
                f"Korelasyon agi guncellendi: {len(self.graph.nodes)} coin, "
                f"{len(self.graph.edges)} baglanti"
            )
            return True
            
        except Exception as e:
            logger.debug(f"Korelasyon agi guncelleme hatasi: {e}")
            return False

    def _fetch_price_data(self, coins: List[str]):
        """CoinGecko'dan son 30 günlük fiyat verilerini çek."""
        self.price_data = {}
        
        for coin in coins:
            coin_id = self.COIN_IDS.get(coin)
            if not coin_id:
                continue
                
            try:
                url = f"{self.COINGECKO_URL}/coins/{coin_id}/market_chart"
                params = {"vs_currency": "usd", "days": 30}
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    prices = [p[1] for p in data.get("prices", [])]
                    if len(prices) >= 10:
                        self.price_data[coin] = prices
                
                time.sleep(0.5)  # Rate limit
                
            except Exception as e:
                logger.debug(f"Fiyat verisi {coin} hatasi: {e}")

    def _calculate_correlations(self):
        """Pearson korelasyon matrisini hesapla."""
        coins = list(self.price_data.keys())
        n = len(coins)
        
        if n < 2:
            return
        
        # En kısa veri uzunluğuna normalize et
        min_len = min(len(self.price_data[c]) for c in coins)
        
        # Günlük getiri hesapla
        returns = {}
        for coin in coins:
            prices = self.price_data[coin][:min_len]
            daily_returns = []
            for i in range(1, len(prices)):
                if prices[i-1] > 0:
                    ret = (prices[i] - prices[i-1]) / prices[i-1]
                    daily_returns.append(ret)
            returns[coin] = daily_returns
        
        # Korelasyon matrisi
        self.correlation_matrix = {}
        for i, coin_a in enumerate(coins):
            for j, coin_b in enumerate(coins):
                if i >= j:
                    continue
                
                ret_a = np.array(returns.get(coin_a, []))
                ret_b = np.array(returns.get(coin_b, []))
                
                min_r = min(len(ret_a), len(ret_b))
                if min_r < 5:
                    continue
                
                corr = np.corrcoef(ret_a[:min_r], ret_b[:min_r])[0, 1]
                
                if not np.isnan(corr):
                    self.correlation_matrix[(coin_a, coin_b)] = round(float(corr), 3)
                    self.correlation_matrix[(coin_b, coin_a)] = round(float(corr), 3)

    def _build_graph(self):
        """Korelasyon matrisinden çizge (graph) oluştur."""
        self.graph = nx.Graph()
        
        # Tüm coinleri düğüm olarak ekle
        for coin in self.price_data.keys():
            self.graph.add_node(coin)
        
        # Güçlü korelasyonlar → kenar (edge)
        for (a, b), corr in self.correlation_matrix.items():
            if a < b and abs(corr) >= 0.5:  # 0.5+ korelasyon = bağlantı
                self.graph.add_edge(
                    a, b,
                    weight=abs(corr),
                    correlation=corr,
                    strength="strong" if abs(corr) >= 0.7 else "moderate",
                )

    def get_correlation(self, coin_a: str, coin_b: str) -> Optional[float]:
        """İki coin arasındaki korelasyonu döndür."""
        if not self.correlation_matrix:
            self.update_network()
        
        return self.correlation_matrix.get((coin_a, coin_b))

    def detect_contagion_risk(self, falling_coin: str) -> Dict:
        """
        Bir coin düştüğünde hangi coinler etkilenir?
        
        Returns:
            {
                'at_risk': [{'coin': str, 'correlation': float, 'risk': str}],
                'safe': [{'coin': str, 'correlation': float}],
                'risk_score': int (0-100)
            }
        """
        if not self.graph or not self.correlation_matrix:
            self.update_network()
        
        if not self.graph or falling_coin not in self.graph:
            return {"at_risk": [], "safe": [], "risk_score": 0}
        
        at_risk = []
        safe = []
        
        for other_coin in self.graph.nodes:
            if other_coin == falling_coin:
                continue
            
            corr = self.correlation_matrix.get((falling_coin, other_coin), 0)
            
            if corr >= 0.7:
                at_risk.append({
                    "coin": other_coin,
                    "correlation": corr,
                    "risk": "HIGH",
                })
            elif corr >= 0.5:
                at_risk.append({
                    "coin": other_coin,
                    "correlation": corr,
                    "risk": "MEDIUM",
                })
            elif abs(corr) < 0.3:
                safe.append({
                    "coin": other_coin,
                    "correlation": corr,
                })
        
        # Risk skoru
        risk_score = 0
        if at_risk:
            avg_corr = sum(r["correlation"] for r in at_risk) / len(at_risk)
            risk_score = int(avg_corr * 100 * len(at_risk) / max(len(self.graph.nodes) - 1, 1))
            risk_score = min(100, risk_score)
        
        if at_risk:
            logger.info(
                f"  Bulasma riski {falling_coin} duserse: "
                f"{len(at_risk)} coin risk altinda, skor={risk_score}"
            )
        
        return {
            "at_risk": sorted(at_risk, key=lambda x: x["correlation"], reverse=True),
            "safe": safe,
            "risk_score": risk_score,
        }

    def find_diversification(self) -> List[Tuple[str, str, float]]:
        """
        Düşük korelasyonlu coin çiftlerini bul (diversifikasyon).
        
        Returns: [(coin_a, coin_b, correlation), ...]
        """
        if not self.correlation_matrix:
            self.update_network()
        
        pairs = []
        seen = set()
        
        for (a, b), corr in self.correlation_matrix.items():
            key = tuple(sorted([a, b]))
            if key in seen:
                continue
            seen.add(key)
            
            if abs(corr) < 0.3:
                pairs.append((a, b, corr))
        
        return sorted(pairs, key=lambda x: abs(x[2]))

    def get_centrality(self) -> Dict[str, float]:
        """Her coin'in ağdaki 'merkezilik' skorunu döndür."""
        if not self.graph or len(self.graph.nodes) == 0:
            return {}
        
        try:
            centrality = nx.degree_centrality(self.graph)
            return {k: round(v, 3) for k, v in 
                    sorted(centrality.items(), key=lambda x: x[1], reverse=True)}
        except Exception:
            return {}

    def get_network_summary(self) -> Dict:
        """Ağ özeti."""
        if not self.graph:
            return {"status": "inactive", "nodes": 0, "edges": 0}
        
        centrality = self.get_centrality()
        most_central = list(centrality.keys())[:3] if centrality else []
        
        return {
            "status": "active",
            "nodes": len(self.graph.nodes),
            "edges": len(self.graph.edges),
            "most_central": most_central,
            "last_update": self.last_update.isoformat() if self.last_update else None,
        }
