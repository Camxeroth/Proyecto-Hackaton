import pandas as pd
import numpy as np
import scipy.stats as stats
from arch import arch_model


class MotorVolatilidadGARCH:
    def __init__(self, retornos_df, dist='t'):
        self.retornos = retornos_df
        self.dist = dist
        self.parametros_mle = {}

    def _calcular_metricas_cola(self, volatilidad_condicional, nu):
        """
        Calcula VaR y CVaR (Expected Shortfall) paramétrico bajo distribución t-Student
        en los horizontes de confianza institucionales 95%, 97.5% y 99%.

        VaR(alpha): cuantil de la distribución de pérdidas a nivel alpha.
        CVaR(alpha): pérdida esperada condicional dado que se supera el VaR.
                     Para t(nu): ES = sigma * t_pdf(t_ppf(alpha,nu), nu) / alpha * (nu + t_ppf^2) / (nu-1)
        """
        niveles = {'95': 0.05, '97_5': 0.025, '99': 0.01}
        resultado = {}

        for etiqueta, alpha_nivel in niveles.items():
            if self.dist == 't':
                z = stats.t.ppf(alpha_nivel, nu)
                # Fórmula exacta del Expected Shortfall para t(nu)
                es_factor = (stats.t.pdf(z, nu) / alpha_nivel) * (nu + z**2) / (nu - 1)
            else:
                z = stats.norm.ppf(alpha_nivel)
                es_factor = stats.norm.pdf(z) / alpha_nivel

            resultado[f'VaR_{etiqueta}'] = volatilidad_condicional * z          # negativo = pérdida
            resultado[f'CVaR_{etiqueta}'] = -volatilidad_condicional * es_factor # positivo = magnitud
        return resultado

    def ejecutar_modelo_en_memoria(self):
        retornos_escalados = self.retornos.iloc[:, 0] * 100

        am = arch_model(retornos_escalados, mean='Zero', vol='Garch', p=1, q=1, dist=self.dist)
        modelo_ajustado = am.fit(update_freq=5, disp='off')

        varianza_condicional    = (modelo_ajustado.conditional_volatility ** 2) / 10000
        volatilidad_condicional = modelo_ajustado.conditional_volatility / 100

        alpha = modelo_ajustado.params.get('alpha[1]', 0)
        beta  = modelo_ajustado.params.get('beta[1]',  0)
        omega = modelo_ajustado.params.get('omega',    0)
        nu    = modelo_ajustado.params.get('nu',       5.0)

        self.parametros_mle = {
            'alpha':        alpha,
            'beta':         beta,
            'omega':        omega,
            'persistencia': alpha + beta,
            'nu':           nu,
            'pvalues':      dict(modelo_ajustado.pvalues),
            # Volatilidad de largo plazo implícita: omega / (1 - alpha - beta)
            'vol_largo_plazo': np.sqrt(omega / (1 - alpha - beta)) if (alpha + beta) < 1 else np.nan,
        }

        metricas_cola = self._calcular_metricas_cola(volatilidad_condicional, nu)

        df_procesado = pd.DataFrame({
            'Retorno_Log':  self.retornos.iloc[:, 0],
            'Varianza_GARCH': varianza_condicional,
            **metricas_cola
        }, index=self.retornos.index)

        return df_procesado, self.parametros_mle

    def ejecutar_walk_forward(self, ventana_min=756, paso=63):
        """
        Re-estima el modelo cada 'paso' días usando únicamente datos históricos
        disponibles en el momento t (ventana expansiva sin data leakage).
        ventana_min ≈ 756 días hábiles = 3 años de historia mínima.
        """
        serie     = self.retornos.iloc[:, 0] * 100
        varianzas = pd.Series(index=serie.index, dtype=float)
        var_95    = pd.Series(index=serie.index, dtype=float)
        cvar_95   = pd.Series(index=serie.index, dtype=float)
        var_975   = pd.Series(index=serie.index, dtype=float)
        cvar_975  = pd.Series(index=serie.index, dtype=float)
        var_99    = pd.Series(index=serie.index, dtype=float)
        cvar_99   = pd.Series(index=serie.index, dtype=float)

        for i in range(ventana_min, len(serie), paso):
            ventana   = serie.iloc[:i]
            am        = arch_model(ventana, mean='Zero', vol='Garch', p=1, q=1, dist=self.dist)
            resultado = am.fit(update_freq=0, disp='off')
            pronostico = resultado.forecast(horizon=paso, reindex=False)
            fin        = min(i + paso, len(serie))

            vol_pred = np.sqrt(pronostico.variance.values[-1][:fin - i]) / 100
            varianzas.iloc[i:fin] = pronostico.variance.values[-1][:fin - i]

            nu_iter = resultado.params.get('nu', 5.0)
            mc      = self._calcular_metricas_cola(vol_pred, nu_iter)

            var_95.iloc[i:fin]   = mc['VaR_95']
            cvar_95.iloc[i:fin]  = mc['CVaR_95']
            var_975.iloc[i:fin]  = mc['VaR_97_5']
            cvar_975.iloc[i:fin] = mc['CVaR_97_5']
            var_99.iloc[i:fin]   = mc['VaR_99']
            cvar_99.iloc[i:fin]  = mc['CVaR_99']

        varianza_final = varianzas / 10000
        df_procesado = pd.DataFrame({
            'Retorno_Log':    self.retornos.iloc[:, 0],
            'Varianza_GARCH': varianza_final,
            'VaR_95':   var_95,   'CVaR_95':  cvar_95,
            'VaR_97_5': var_975,  'CVaR_97_5':cvar_975,
            'VaR_99':   var_99,   'CVaR_99':  cvar_99,
        }, index=self.retornos.index).dropna()

        # Parámetros MLE sobre serie completa — únicamente para la capa de presentación
        _, self.parametros_mle = self.ejecutar_modelo_en_memoria()
        return df_procesado, self.parametros_mle

    def comparar_con_gjr(self):
        """Compara GARCH(1,1) simétrico vs GJR-GARCH(1,1,1) por AIC y BIC."""
        s = self.retornos.iloc[:, 0] * 100
        simetrico  = arch_model(s, mean='Zero', vol='Garch', p=1, q=1,      dist=self.dist).fit(disp='off')
        asimetrico = arch_model(s, mean='Zero', vol='Garch', p=1, o=1, q=1, dist=self.dist).fit(disp='off')
        return {
            'GARCH(1,1)':     {'AIC': round(simetrico.aic,  2), 'BIC': round(simetrico.bic,  2)},
            'GJR-GARCH(1,1)': {'AIC': round(asimetrico.aic, 2), 'BIC': round(asimetrico.bic, 2)},
        }


def evaluar_persistencia(alpha, beta, umbral=0.999):
    """
    Diagnostica la estacionariedad de la varianza condicional.
    alpha+beta >= 1 implica un proceso IGARCH (varianza integrada): la
    volatilidad no revierte a media y el modelo pierde validez econométrica.
    """
    persistencia = alpha + beta
    return {
        'persistencia':    persistencia,
        'es_estacionaria': persistencia < umbral,
        'interpretacion': (
            "Proceso estacionario: la varianza condicional revierte a su nivel de largo plazo. "
            "El modelo GARCH es econométricamente válido para este activo y ventana temporal."
            if persistencia < umbral else
            "Persistencia extrema (alpha+beta >= 1): proceso tipo IGARCH detectado. "
            "La varianza condicional no revierte a la media; el modelo puede sobreestimar "
            "la persistencia de choques y sub-estimar la capacidad de recuperación del activo."
        )
    }