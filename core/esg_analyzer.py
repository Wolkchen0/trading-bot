"""
ESG Analyzer — Kripto Çevresel, Sosyal ve Yönetişim Skorlama

Kripto varlıkların ESG (Environmental, Social, Governance) skorlarını
dahili veritabanı ve CoinGecko verilerinden hesaplar.
"""
import time
import requests
from typing import Dict, Optional
from utils.logger import logger


class ESGAnalyzer:
    """
    Kripto ESG skorlama motoru.
    
    Kriterler:
      E (Environment): Konsensüs mekanizması, enerji verimliliği
      S (Social): Topluluk büyüklüğü, GitHub aktivitesi, geliştirici sayısı
      G (Governance): Merkeziyetsizlik, şeffaflık, governance yapısı
    
    Skor: -30 ile +30 arası (her kategori -10 ile +10)
    """

    # Dahili kripto ESG veritabanı
    # Her kategori: -10 (çok kötü) ile +10 (mükemmel)
    CRYPTO_ESG = {
        # --- TIER 1: Yüksek ESG ---
        "ETH": {
            "E": 8, "S": 9, "G": 8, "total": 83,
            "notes": "PoS, dev ekosistem, güçlü yönetişim (EIP)",
            "consensus": "PoS",
        },
        "ADA": {
            "E": 9, "S": 7, "G": 7, "total": 77,
            "notes": "PoS Ouroboros, akademik peer-review, Catalyst yönetişim",
            "consensus": "PoS",
        },
        # --- TIER 2: İyi ESG ---
        "SOL": {
            "E": 7, "S": 7, "G": 5, "total": 63,
            "notes": "PoH+PoS, hızlı ama tartışmalı downtime geçmişi",
            "consensus": "PoH/PoS",
        },
        "DOT": {
            "E": 7, "S": 6, "G": 8, "total": 70,
            "notes": "NPoS, on-chain governance, parachain ekosistemi",
            "consensus": "NPoS",
        },
        "LINK": {
            "E": 6, "S": 8, "G": 6, "total": 67,
            "notes": "Oracle ağı, DeFi altyapısı, aktif geliştirme",
            "consensus": "N/A (Oracle)",
        },
        "AVAX": {
            "E": 7, "S": 6, "G": 6, "total": 63,
            "notes": "Snow konsensüs, subnet esnekliği",
            "consensus": "Snow",
        },
        "UNI": {
            "E": 7, "S": 7, "G": 8, "total": 73,
            "notes": "DEX, DAO yönetişimi, topluluk kontrolü",
            "consensus": "N/A (DEX)",
        },
        "AAVE": {
            "E": 7, "S": 7, "G": 8, "total": 73,
            "notes": "DeFi lending, DAO, güvenlik odaklı",
            "consensus": "N/A (DeFi)",
        },
        # --- TIER 3: Orta ESG ---
        "BTC": {
            "E": -5, "S": 9, "G": 8, "total": 40,
            "notes": "PoW yüksek enerji, ama en güvenilir ve merkeziyetsiz",
            "consensus": "PoW",
        },
        "LTC": {
            "E": -3, "S": 5, "G": 5, "total": 23,
            "notes": "PoW ama Scrypt daha verimli, köklü topluluk",
            "consensus": "PoW",
        },
        "XRP": {
            "E": 8, "S": 5, "G": -3, "total": 33,
            "notes": "Düşük enerji ama çok merkezi, SEC davası",
            "consensus": "RPCA",
        },
        # --- TIER 4: Düşük ESG ---
        "DOGE": {
            "E": -4, "S": 7, "G": 1, "total": 13,
            "notes": "PoW, güçlü topluluk ama zayıf yönetişim, Musk etkisi",
            "consensus": "PoW",
        },
        "SHIB": {
            "E": 5, "S": 6, "G": 0, "total": 37,
            "notes": "ERC-20 (ETH üzerinde), meme coin, ShibaSwap ekosistemi",
            "consensus": "N/A (ERC-20)",
        },
        "PEPE": {
            "E": 5, "S": 4, "G": -3, "total": 20,
            "notes": "ERC-20, meme coin, yönetişim yok, spekülatif",
            "consensus": "N/A (ERC-20)",
        },
        "BONK": {
            "E": 7, "S": 4, "G": -2, "total": 30,
            "notes": "Solana üzerinde, meme coin, topluluk driven",
            "consensus": "N/A (SPL)",
        },
        "WIF": {
            "E": 7, "S": 3, "G": -3, "total": 23,
            "notes": "Solana meme, çok yeni, yönetişim yok",
            "consensus": "N/A (SPL)",
        },
        "TRUMP": {
            "E": 5, "S": 3, "G": -5, "total": 10,
            "notes": "Politik meme coin, çok merkezi, spekülatif",
            "consensus": "N/A",
        },
    }

    # Varsayılan ESG (bilinmeyen coinler için)
    DEFAULT_ESG = {
        "E": 0, "S": 3, "G": 0, "total": 10,
        "notes": "Bilinmeyen coin, varsayılan ESG",
        "consensus": "Unknown",
    }

    def __init__(self):
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 3600  # 1 saat
        logger.info(f"ESG Analyzer baslatildi — {len(self.CRYPTO_ESG)} coin veritabaninda")

    def get_esg_score(self, symbol: str) -> Dict:
        """
        Coin'in ESG skorunu döndür.
        
        Returns:
            {
                'E': int, 'S': int, 'G': int,
                'total': int (0-100),
                'risk_level': str,
                'consensus': str,
                'notes': str
            }
        """
        coin = symbol.replace("/USD", "").replace("USD", "")
        
        # Veritabanından çek
        esg_data = self.CRYPTO_ESG.get(coin, self.DEFAULT_ESG)
        
        # Risk seviyesi hesapla
        total = esg_data["total"]
        if total >= 70:
            risk_level = "LOW"
            risk_label = "Düşük Risk"
        elif total >= 50:
            risk_level = "MEDIUM"
            risk_label = "Orta Risk"
        elif total >= 30:
            risk_level = "ELEVATED"
            risk_label = "Yüksek Risk"
        else:
            risk_level = "HIGH"
            risk_label = "Çok Yüksek Risk"

        result = {
            "E": esg_data["E"],
            "S": esg_data["S"],
            "G": esg_data["G"],
            "total": total,
            "risk_level": risk_level,
            "risk_label": risk_label,
            "consensus": esg_data.get("consensus", "Unknown"),
            "notes": esg_data.get("notes", ""),
        }

        logger.debug(
            f"  ESG {coin}: E={esg_data['E']} S={esg_data['S']} "
            f"G={esg_data['G']} Total={total}/100 -> {risk_level}"
        )

        return result

    def get_esg_adjusted_signal(self, symbol: str, base_score: float) -> Dict:
        """
        Base sinyali ESG ile ayarla.
        
        ESG yüksek → sinyal güçlenir (güvenli yatırım)
        ESG düşük → sinyal zayıflar (riskli)
        
        Returns:
            {
                'adjusted_score': float,
                'esg_multiplier': float,
                'esg_total': int
            }
        """
        esg = self.get_esg_score(symbol)
        total = esg["total"]
        
        # ESG çarpanı: 0.80 (kötü) - 1.15 (mükemmel)
        if total >= 70:
            multiplier = 1.15  # Yüksek ESG → sinyal %15 güçlenir
        elif total >= 50:
            multiplier = 1.05  # İyi ESG → %5 güçlenir
        elif total >= 30:
            multiplier = 0.95  # Orta ESG → %5 zayıflar
        else:
            multiplier = 0.85  # Düşük ESG → %15 zayıflar
        
        adjusted = base_score * multiplier
        
        return {
            "adjusted_score": round(adjusted, 2),
            "esg_multiplier": multiplier,
            "esg_total": total,
            "esg_risk": esg["risk_level"],
        }

    def compare_coins(self, symbols: list) -> list:
        """Birden fazla coin'i ESG'ye göre sırala."""
        results = []
        for s in symbols:
            esg = self.get_esg_score(s)
            results.append({"symbol": s, **esg})
        return sorted(results, key=lambda x: x["total"], reverse=True)
