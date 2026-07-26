import sys
import os
import pandas as pd
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from scripts.ingestion import IngestorMercado
from scripts.motor_garch import MotorVolatilidadGARCH
from scripts.backtester import BacktesterGARCH

# Simular SPY original
ing = IngestorMercado('SPY', '2015-01-01', '2026-06-01')
df_ret = ing.procesar_datos_en_memoria()
mot = MotorVolatilidadGARCH(df_ret)
df_proc, _ = mot.ejecutar_modelo_en_memoria()
back = BacktesterGARCH(df_proc)
back.simular()
m = back.obtener_metricas()
print(f"MDD_Estrategia (nuevo expandiente): {m['MDD_Estrategia']:.2f}%")
print(f"Retorno_Estrategia (nuevo expandiente): {m['Retorno_Estrategia']:.2f}%")
print(f"MDD_Mercado: {m['MDD_Mercado']:.2f}%")
print(f"Retorno_Mercado: {m['Retorno_Mercado']:.2f}%")
