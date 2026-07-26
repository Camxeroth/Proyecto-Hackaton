import boto3
import json
import logging
from botocore.exceptions import NoCredentialsError, ClientError

logger = logging.getLogger(__name__)


class AnalistaRiesgoBedrock:
    """
    Motor de análisis cualitativo de riesgo respaldado por Amazon Bedrock.
    Genera reportes ejecutivos contextualizados a partir de las métricas
    cuantitativas del modelo GARCH.

    Si las credenciales de AWS no están disponibles en el entorno, el sistema
    degrada de forma elegante a un motor de reporte local (fallback).
    """

    MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

    def __init__(self, region_name="us-east-1"):
        self.region_name = region_name
        try:
            self.client  = boto3.client("bedrock-runtime", region_name=self.region_name)
            self.is_ready = True
        except Exception as e:
            logger.warning("Bedrock no disponible: %s. Activando modo local.", e)
            self.is_ready = False

    def generar_reporte_riesgo(self, ticker: str, metricas: dict, parametros: dict) -> str:
        """
        Invoca Claude 3 Haiku en Bedrock con contexto cuantitativo del modelo.

        El prompt está diseñado para producir un informe ejecutivo de nivel
        senior — sin lenguaje coloquial — siguiendo el estándar de memorandos
        de riesgo de gestoras de activos institucionales.
        """
        persistencia   = parametros['persistencia']
        nu             = parametros['nu']
        mdd_est        = metricas['MDD_Estrategia']
        mdd_mkt        = metricas['MDD_Mercado']
        ret_est        = metricas['Retorno_Estrategia']
        ret_mkt        = metricas['Retorno_Mercado']
        reduccion_mdd  = abs(mdd_mkt) - abs(mdd_est)
        alfa_neto      = ret_est - ret_mkt        # puede ser negativo, expected

        prompt = f"""Actúas como un analista cuantitativo senior de una gestora de activos de primer nivel.
Tu tarea es redactar un memorando de riesgo ejecutivo, conciso y técnico, de exactamente dos párrafos.
El tono debe ser profesional, preciso y orientado a la toma de decisiones tácticas.
No uses viñetas, encabezados adicionales ni saludos.

CONTEXTO DEL MODELO — Activo: {ticker}
─────────────────────────────────────────────────────
Modelo: GARCH(1,1) con innovaciones t-Student
  · Persistencia (α+β):              {persistencia:.4f}
  · Grados de libertad (ν):          {nu:.2f}  ← cola pesada si ν < 6

Backtest walk-forward (sin look-ahead bias):
  · Drawdown máximo — Estrategia:    {mdd_est:.2f}%
  · Drawdown máximo — Buy & Hold:    {mdd_mkt:.2f}%
  · Reducción de drawdown:           {reduccion_mdd:.2f} p.p.
  · Rendimiento — Estrategia:        {ret_est:.2f}%
  · Rendimiento — Buy & Hold:        {ret_mkt:.2f}%
  · Alfa neto vs. mercado pasivo:    {alfa_neto:+.2f} p.p.
─────────────────────────────────────────────────────

Párrafo 1: Interpreta la dinámica de la volatilidad del activo a la luz de los parámetros GARCH.
  Menciona si los clústeres de volatilidad son persistentes, qué implica ν bajo para la gestión de
  riesgo de cola y qué justifica el uso de una distribución t-Student frente a la normal estándar.

Párrafo 2: Evalúa la eficacia de la estrategia táctica. Comenta la reducción de drawdown obtenida,
  el costo de oportunidad en términos de alfa neto y si la relación riesgo-retorno justifica la
  adopción del modelo frente a una estrategia pasiva. Cierra con una recomendación táctica concreta."""

        if not self.is_ready:
            return self._reporte_local(ticker, persistencia, nu, reduccion_mdd, alfa_neto, mdd_est, ret_est)

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 600,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}]
            })
            response = self.client.invoke_model(
                body=body,
                modelId=self.MODEL_ID,
                accept="application/json",
                contentType="application/json"
            )
            data = json.loads(response["body"].read())
            return data["content"][0]["text"]

        except (NoCredentialsError, ClientError) as e:
            logger.warning("Error de acceso a Bedrock: %s", e)
            return self._reporte_local(ticker, persistencia, nu, reduccion_mdd, alfa_neto, mdd_est, ret_est)
        except Exception as e:
            logger.error("Error inesperado al invocar Bedrock: %s", e)
            return self._reporte_local(ticker, persistencia, nu, reduccion_mdd, alfa_neto, mdd_est, ret_est)

    @staticmethod
    def _reporte_local(ticker, persistencia, nu, reduccion_mdd, alfa_neto, mdd_est, ret_est) -> str:
        """
        Motor de reporte local. Se activa cuando Bedrock no está disponible.
        Genera un análisis determinístico basado en los rangos paramétricos observados.
        """
        cola = "pronunciadas, consistentes con un proceso leptocúrtico" if nu < 6 else "moderadas, próximas a la distribución normal"
        regimen = "alta persistencia" if persistencia > 0.97 else "persistencia moderada"

        return (
            f"**Análisis de Volatilidad — {ticker}** "
            f"*(Generado localmente — conector AWS Bedrock no disponible)*\n\n"
            f"El proceso GARCH(1,1) estimado para {ticker} evidencia un régimen de {regimen} "
            f"en la varianza condicional (α+β = {persistencia:.4f}), lo que implica que los choques de "
            f"volatilidad se disipan lentamente a lo largo del tiempo y justifican una gestión activa del "
            f"riesgo de exposición. Los grados de libertad estimados (ν = {nu:.2f}) señalan colas {cola}, "
            f"lo que valida la elección de la distribución t-Student frente a innovaciones gaussianas y "
            f"refuerza la necesidad de métricas de cola pesada como el CVaR para dimensionar el riesgo real.\n\n"
            f"La estrategia táctica de reducción de exposición ha demostrado una capacidad de preservación "
            f"de capital significativa, recortando el Drawdown Máximo en {reduccion_mdd:.2f} p.p. respecto "
            f"al índice de referencia (MDD Estrategia: {mdd_est:.2f}%). El alfa neto acumulado es de "
            f"{alfa_neto:+.2f} p.p. frente a la estrategia pasiva, resultado que refleja el costo de "
            f"oportunidad inherente a los períodos de liquidez táctica. Para el próximo rebalanceo, se "
            f"recomienda mantener los umbrales actuales y revisar la ventana de re-estimación walk-forward "
            f"si el régimen de volatilidad presenta un cambio estructural."
        )
