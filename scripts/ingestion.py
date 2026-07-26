import yfinance as yf
import pandas as pd
import numpy as np
import boto3
import io

class IngestorMercado:
    def __init__(self, ticker, fecha_inicio, fecha_fin):
        self.ticker = ticker
        self.fecha_inicio = fecha_inicio
        self.fecha_fin = fecha_fin

    def procesar_datos_en_memoria(self):
        """Descarga y transforma los datos directamente en RAM."""
        df_completo = yf.download(self.ticker, start=self.fecha_inicio, end=self.fecha_fin, auto_adjust=True)
        
        if 'Close' in df_completo.columns:
            df = df_completo['Close']
        else:
            raise KeyError(f"La API no devolvió la columna 'Close' para {self.ticker}.")
            
        if isinstance(df, pd.Series):
            df = df.to_frame(name=self.ticker)
            
        df = df.ffill().dropna()
        
        # Transformación a retornos logarítmicos
        df_log = np.log(df / df.shift(1)).dropna()
        
        return df_log

    def procesar_datos_con_cache_s3(self, bucket_name):
        s3 = boto3.client('s3')
        key = f"retornos/{self.ticker}_{self.fecha_inicio}_{self.fecha_fin}.parquet"
        try:
            obj = s3.get_object(Bucket=bucket_name, Key=key)
            return pd.read_parquet(io.BytesIO(obj['Body'].read()))
        except s3.exceptions.NoSuchKey:
            df_log = self.procesar_datos_en_memoria()
            buffer = io.BytesIO()
            df_log.to_parquet(buffer)
            s3.put_object(Bucket=bucket_name, Key=key, Body=buffer.getvalue())
            return df_log