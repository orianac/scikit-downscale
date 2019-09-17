import collections

import numpy as np
import pandas as pd

from sklearn.base import RegressorMixin
from sklearn.linear_model.base import LinearModel

from .utils import QuantileMapper, ensure_samples_features

MONTH_GROUPER = lambda x: x.month
      

class BcsdBase(LinearModel, RegressorMixin):
    ''' Base class for BCSD model. 
    '''

    def __init__(self, time_grouper=MONTH_GROUPER, **qm_kwargs):
        if isinstance(time_grouper, str):
            self.grouper_ = pd.Grouper(freq=time_grouper)
        else:
            self.grouper_ = time_grouper

        self.qm_kwargs = qm_kwargs
        self.quantile_mappers_ = {}

    def _qm_fit_by_group(self, groups):
        ''' helper function to fit quantile mappers by group

        Note that we store these mappers for later
        '''
        for key, group in groups:
            data = ensure_samples_features(group)
            self.quantile_mappers_[key] = QuantileMapper(**self.qm_kwargs).fit(data)

    def _qm_transform_by_group(self, groups):
        ''' helper function to apply quantile mapping by group

        Note that we recombine the dataframes using pd.concat, there may be a better way to do this
        '''

        dfs = []
        for key, group in groups:
            data = ensure_samples_features(group)
            qmapped = self.quantile_mappers_[key].transform(data)
            dfs.append(pd.DataFrame(qmapped, index=group.index))
        return pd.concat(dfs).sort_index()

    def _remove_climatology(self, obj, climatology):
        dfs = []
        for key, group in obj.groupby(self.grouper_):
            dfs.append(group - climatology.loc[key])
        
        out = pd.concat(dfs).sort_index()
        assert obj.shape == out.shape
        return out

class BcsdPrecipitation(BcsdBase):
    ''' Classic BCSD model for Precipitation

    Parameters
    ----------
    time_grouper : str or pd.Grouper, optional
        Pandas time frequency str or Grouper object. Specifies how to group
        time periods. Default is 'M' (e.g. Monthly).
    **qm_kwargs
        Keyword arguments to pass to QuantileMapper.

    Attributes
    ----------
    grouper_ : pd.Grouper
        Linear Regression object.
    quantile_mappers_ : dict
        QuantileMapper objects (one for each time group).
    '''
    def fit(self, X, y):
        ''' Fit BcsdPrecipitation model

        Parameters
        ----------
        X : pd.Series or pd.DataFrame, shape (n_samples, 1)
            Training data
        y : pd.Series or pd.DataFrame, shape (n_samples, 1)
            Target values.

        Returns
        -------
        self : returns an instance of self.
        '''
        y_groups = y.groupby(self.grouper_)
        # calculate the climatologies
        self._y_climo = y_groups.mean()
        if self._y_climo.min() <= 0:
            raise ValueError("Invalid value in target climatology")

        # fit the quantile mappers
        self._qm_fit_by_group(y_groups)

        return self

    def predict(self, X):
        '''Predict using the BcsdPrecipitation model

        Parameters
        ----------
        X : pd.Series or pd.DataFrame, shape (n_samples, 1)
            Samples.

        Returns
        -------
        C : pd.DataFrame, shape (n_samples, 1)
            Returns predicted values.
        '''
        X = ensure_samples_features(X)

        # Bias correction
        # apply quantile mapping by month
        Xqm = self._qm_transform_by_group(X.groupby(self.grouper_))

        # calculate the anomalies as a ratio of the training data
        return Xqm.groupby(self.grouper_) / self._y_climo


class BcsdTemperature(BcsdBase):
    def fit(self, X, y):
        ''' Fit BcsdTemperature model

        Parameters
        ----------
        X : pd.Series or pd.DataFrame, shape (n_samples, 1)
            Training data
        y : pd.Series or pd.DataFrame, shape (n_samples, 1)
            Target values.

        Returns
        -------
        self : returns an instance of self.
        '''
        # calculate the climatologies
        self._x_climo = X.groupby(self.grouper_).mean()
        y_groups = y.groupby(self.grouper_)
        self._y_climo = y_groups.mean()

        # fit the quantile mappers
        self._qm_fit_by_group(y_groups)

        return self

    def predict(self, X):
        ''' Predict using the BcsdTemperature model

        Parameters
        ----------
        X : DataFrame, shape (n_samples, 1)
            Samples.

        Returns
        -------
        C : pd.DataFrame, shape (n_samples, 1)
            Returns predicted values.
        '''
        X = ensure_samples_features(X)

        # Calculate the 9-year running mean for each month
        def rolling_func(x):
            return x.rolling(9, center=True, min_periods=1).mean()
        X_rolling_mean = X.groupby(self.grouper_).apply(rolling_func)

        # calc shift
        # why isn't this working??
        # X_shift = X_rolling_mean.groupby(self.grouper_) - self._x_climo
        X_shift = self._remove_climatology(X_rolling_mean, self._x_climo)

        # remove shift
        X_no_shift = X - X_shift

        # Bias correction
        # apply quantile mapping by month
        Xqm = self._qm_transform_by_group(X_no_shift.groupby(self.grouper_))

        # restore the shift
        X_qm_with_shift = Xqm + X_shift

        # calculate the anomalies
        return self._remove_climatology(X_qm_with_shift, self._y_climo)
