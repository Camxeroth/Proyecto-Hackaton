import pandas as pd
import numpy as np

class BacktesterGARCH:
    def __init__(self, df_procesado):
        self.df = df_procesado.copy()
        self.volatilidad = self.df['Varianza_GARCH']
        self.retornos = self.df['Retorno_Log']
        self.resultados = None

    def calcular_drawdown(self, serie_acumulada):
        picos = serie_acumulada.cummax()
        drawdowns = (serie_acumulada - picos) / picos
        return drawdowns.min() * 100 

    def simular(self, pct_salida=95, pct_entrada=70, ventana_min=252):
        vol = self.volatilidad
        estados = []
        estado_actual = 1 

        for i, (fecha, v) in enumerate(vol.items()):
            if i < ventana_min or pd.isna(v):
                estados.append(estado_actual)
                continue
                
            historico = vol.iloc[:i]  # SOLO pasado, nunca el valor actual ni futuro
            umbral_salida = np.percentile(historico.dropna(), pct_salida)
            umbral_entrada = np.percentile(historico.dropna(), pct_entrada)
            
            if v >= umbral_salida:
                estado_actual = 0  
            elif v <= umbral_entrada and estado_actual == 0:
                estado_actual = 1  
                
            estados.append(estado_actual)

        self.df['Estado'] = estados
        self.df['Retorno_Estrategia'] = self.df['Retorno_Log'] * self.df['Estado']

        self.df['Eq_Mercado'] = np.exp(self.df['Retorno_Log'].cumsum())
        self.df['Eq_Estrategia'] = np.exp(self.df['Retorno_Estrategia'].cumsum())

        self.resultados = self.df
        return self.resultados

    def obtener_metricas(self):
        mdd_mercado = self.calcular_drawdown(self.resultados['Eq_Mercado'])
        mdd_estrategia = self.calcular_drawdown(self.resultados['Eq_Estrategia'])
        retorno_mercado = (self.resultados['Eq_Mercado'].iloc[-1] - 1) * 100
        retorno_estrategia = (self.resultados['Eq_Estrategia'].iloc[-1] - 1) * 100

        return {
            "MDD_Mercado": mdd_mercado,
            "MDD_Estrategia": mdd_estrategia,
            "Retorno_Mercado": retorno_mercado,
            "Retorno_Estrategia": retorno_estrategia
        }