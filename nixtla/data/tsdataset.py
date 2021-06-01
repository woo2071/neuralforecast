# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/data__tsdataset.ipynb (unless otherwise specified).

__all__ = ['TimeSeriesDataset', 'get_default_mask_df']

# Cell
import gc
import logging
from typing import Dict, List, Optional, Tuple, Union
from typing_extensions import Literal

import numpy as np
import pandas as pd
import torch as t
from fastcore.foundation import patch
from torch.utils.data import Dataset

# Cell
class TimeSeriesDataset(Dataset):
    """
    A class used to store Time Series data.
    """

    def __init__(self,
                 Y_df: pd.DataFrame,
                 X_df: Optional[pd.DataFrame] = None,
                 S_df: Optional[pd.DataFrame] = None,
                 f_cols: Optional[List] = None,
                 mask_df: Optional[pd.DataFrame] = None,
                 ds_in_test: int = 0,
                 is_test: bool = False,
                 input_size: int = 15,
                 output_size: int = 1,
                 window_sampling_limit: int = 20,
                 idx_to_sample_freq: int = 1,
                 complete_inputs: bool = False,
                 complete_outputs: bool = True,
                 len_sample_chunks: Optional[int] = None,
                 mode: Literal['simple', 'full'] = 'simple',
                 skip_nonsamplable: bool = False,
                 last_samplable_window: bool = False,
                 verbose: bool = False) -> 'TimeSeriesDataset':
        """
        Parameters
        ----------
        Y_df: pd.DataFrame
            Target time series with columns ['unique_id', 'ds', 'y'].
        X_df: pd.DataFrame
            Exogenous time series with columns ['unique_id', 'ds', 'y'].
        S_df: pd.DataFrame
            Static exogenous variables with columns ['unique_id', 'ds']
            and static variables.
        f_cols: list
            List of exogenous variables of the future.
        mask_df: pd.DataFrame
            Outsample mask with columns ['unique_id', 'ds', 'sample_mask']
            and optionally 'available_mask'.
            Default None: constructs default mask based on ds_in_test.
        ds_in_test: int
            Only used when mask_df = None.
            Numer of datestamps to use as outsample.
        is_test: bool
            Only used when mask_df = None.
            Wheter target time series belongs to test set.
        input_size: int
            Size of the training sets.
        output_size: int
            Forecast horizon.
        window_sampling_limit: int
            Max size of observations to consider, including output_size.
        idx_to_sample_freq: int
            Step size to construct windows.
            Ej. if idx_to_sample_freq=7, each 7 timestamps
            a window will be constructed.
        complete_inputs: bool
            Whether consider only windows with available window_size.
            Default False.
        complete_outputs: bool
            Whether consider only windows with available output_size + 1.
            Default True.
        len_sample_chunks: Optional[int] = None
            Size of complete windows.
            Only used for mode = 'full'!
            Default None, equals to input_size + ouput_size.
        mode: str
            Mode to be used.
            One of ['simple', 'full'].
            If 'simple', windows of size input_size + output_size
            will be constrcuted. If 'full', windows of size
            len_sample_chunks will be constructed.
        skip_nonsamplable: bool
            If `True`, the method `__getitem__` will skip
            non-samplable series and return windows of
            samplable series selected randomly.
        last_samplable_window: bool
            If `True` returns the last samplable
            window.
            Default `False`.
        verbose: bool
            Wheter or not log outputs.
        """
        assert type(Y_df) == pd.core.frame.DataFrame
        assert all([(col in Y_df) for col in ['unique_id', 'ds', 'y']])
        self.verbose = verbose

        if X_df is not None:
            assert type(X_df) == pd.core.frame.DataFrame
            assert all([(col in X_df) for col in ['unique_id', 'ds']])
            assert len(Y_df)==len(X_df), 'The dimensions of Y_df and X_df are not the same'

        if mask_df is not None:
            assert len(Y_df)==len(mask_df), 'The dimensions of Y_df and mask_df are not the same'
            assert all([(col in mask_df) for col in ['unique_id', 'ds', 'sample_mask']])
            if 'available_mask' not in mask_df.columns:
                if self.verbose:
                    logging.info('Available mask not provided, defaulted with 1s.')
                mask_df['available_mask'] = 1
            assert np.sum(np.isnan(mask_df.available_mask.values)) == 0
            assert np.sum(np.isnan(mask_df.sample_mask.values)) == 0
        else:
            mask_df = get_default_mask_df(Y_df=Y_df,
                                          is_test=is_test,
                                          ds_in_test=ds_in_test)

        n_ds  = len(mask_df)
        n_avl = mask_df.available_mask.sum()
        n_ins = mask_df.sample_mask.sum()
        n_out = len(mask_df) - mask_df.sample_mask.sum()

        avl_prc = np.round((100 * n_avl) / n_ds, 2)
        ins_prc = np.round((100 * n_ins) / n_ds, 2)
        out_prc = np.round((100 * n_out) / n_ds, 2)
        if self.verbose:
            logging.info('Train Validation splits\n')
            if len(mask_df.unique_id.unique()) < 10:
                logging.info(mask_df.groupby(['unique_id', 'sample_mask']).agg({'ds': ['min', 'max']}))
            else:
                logging.info(mask_df.groupby(['sample_mask']).agg({'ds': ['min', 'max']}))
            dataset_info  = f'\nTotal data \t\t\t{n_ds} time stamps \n'
            dataset_info += f'Available percentage={avl_prc}, \t{n_avl} time stamps \n'
            dataset_info += f'Insample  percentage={ins_prc}, \t{n_ins} time stamps \n'
            dataset_info += f'Outsample percentage={out_prc}, \t{n_out} time stamps \n'
            logging.info(dataset_info)

        if len_sample_chunks is not None:
            if len_sample_chunks < input_size + output_size:
                raise Exception(f'Insufficient len of sample chunks {len_sample_chunks}')
            self.len_sample_chunks = len_sample_chunks
        else:
            self.len_sample_chunks = input_size + output_size

        self.ts_data, self.s_data, self.meta_data, self.t_cols, self.s_cols \
                         = self._df_to_lists(Y_df=Y_df, S_df=S_df, X_df=X_df, mask_df=mask_df)

        # Dataset attributes
        self.n_series = len(self.ts_data)
        self.max_len = max([len(ts) for ts in self.ts_data])
        self.n_channels = len(self.t_cols) # t_cols insample_mask and outsample_mask
        self.frequency = pd.infer_freq(Y_df.head()['ds'])
        self.f_cols = f_cols
        self.f_idxs = self._get_f_idxs(f_cols) if f_cols else []
        self.window_sampling_limit = window_sampling_limit
        self.input_size = input_size
        self.output_size = output_size
        self.complete_inputs = complete_inputs
        self.complete_outputs = complete_outputs
        self.idx_to_sample_freq = idx_to_sample_freq
        self.mode = mode
        self.skip_nonsamplable = skip_nonsamplable
        self.last_samplable_window = last_samplable_window
        self.first_ds = max(self.max_len - self.window_sampling_limit, 0)

        # Number of X and S features
        self.n_x = 0 if X_df is None else X_df.shape[1] - 2 # -2 for unique_id and ds
        self.n_s = 0 if S_df is None else S_df.shape[1] - 1 # -1 for unique_id

        # Balances panel and creates
        # numpy  s_matrix of shape (n_series, n_s)
        # numpy ts_tensor of shape (n_series, n_channels, max_len) n_channels = t_cols + masks
        self.ts_tensor, self.s_matrix, self.len_series = self._create_tensor(self.ts_data, self.s_data)

        # Defining windows attributes by model
        self.windows_size: int
        self.padding: Tuple[int, int]

        self._define_attributes_by_mode()

        # Defining sampleable time series
        self.ts_idxs = np.arange(self.n_series)
        self.samplable_ts_idxs: np.ndarray
        self.n_samplable_ts: int

        self._define_samplable_ts_idxs()

# Cell
@patch
def _define_attributes_by_mode(self: TimeSeriesDataset):
    if self.mode in ['simple']:
        self.windows_size = self.input_size + self.output_size
        self.padding = (self.input_size, self.output_size)
    elif self.mode in ['full']:
        self.windows_size = self.len_sample_chunks
        self.padding = (0, 0)
    else:
        raise Exception(f'There is no window strategy for {self.mode}')

    assert self.windows_size <= self.window_sampling_limit, (
        'Window sampling limit should be at least input_size + output_size '
        'for simple mode or at least len_sample_chunks for full mode.'
    )

# Cell
@patch
def _define_samplable_ts_idxs(self: TimeSeriesDataset):
    sum_sample_mask = self.ts_tensor[:, self.t_cols.index('sample_mask')] \
                          .sum(axis=1)
    if self.complete_inputs:
        min_mask = self.windows_size
    else:
        min_mask = self.output_size
    self.samplable_ts_idxs = np.argwhere(sum_sample_mask > min_mask).reshape(1, -1)[0]
    self.n_samplable_ts = self.samplable_ts_idxs.size

# Cell
@patch
def _df_to_lists(self: TimeSeriesDataset,
                 S_df: pd.DataFrame,
                 Y_df: pd.DataFrame,
                 X_df: pd.DataFrame,
                 mask_df: pd.DataFrame) -> Tuple[List[np.ndarray],
                                                 List[np.ndarray],
                                                 List[np.ndarray],
                                                 List[str],
                                                 List[str]]:
    """Transforms input dataframes to lists.

    Parameters
    ----------
    S_df: pd.DataFrame
        Static exogenous variables with columns ['unique_id', 'ds']
        and static variables.
    Y_df: pd.DataFrame
        Target time series with columns ['unique_id', 'ds', 'y'].
    X_df: pd.DataFrame
        Exogenous time series with columns ['unique_id', 'ds', 'y'].
    mask_df: pd.DataFrame
        Outsample mask with columns ['unique_id', 'ds', 'sample_mask']
        and optionally 'available_mask'.
        Default None: constructs default mask based on ds_in_test.

    Returns
    -------
    Tuple of five lists:
        - List of time series. Each element of the list is a
          numpy array of shape (length of the time series, n_channels),
          where n_channels = t_cols + masks.
        - List of static variables. Each element of the list is a
          numpy array of shape (1, n_s).
          where n_channels = t_cols + masks.
        - List of meta data. Each element of the list is a
          numpy array of shape (lenght of the time series, 2)
          and corresponds to unique_id, ds.
        - List of temporal variables (including target and masks).
        - List of statitc variables.
    """
    # None protections
    if X_df is None:
        X_df = Y_df[['unique_id', 'ds']]

    if S_df is None:
        S_df = Y_df[['unique_id']].drop_duplicates()

    # Protect order of data
    Y = Y_df.sort_values(by=['unique_id', 'ds'], ignore_index=True).copy()
    X = X_df.sort_values(by=['unique_id', 'ds'], ignore_index=True).copy()
    M = mask_df.sort_values(by=['unique_id', 'ds'], ignore_index=True).copy()

    assert np.array_equal(X.unique_id.values, Y.unique_id.values), f'Mismatch in X, Y unique_ids'
    assert np.array_equal(X.ds.values, Y.ds.values), f'Mismatch in X, Y ds'
    assert np.array_equal(M.unique_id.values, Y.unique_id.values), f'Mismatch in M, Y unique_ids'
    assert np.array_equal(M.ds.values, Y.ds.values), f'Mismatch in M, Y ds'

    # Create bigger grouped by dataframe G to parse
    M = M[['available_mask', 'sample_mask']]
    X.drop(['unique_id', 'ds'], 1, inplace=True)
    G = Y.join(X).join(M)

    S = S_df.sort_values(by=['unique_id']).copy()

    # time columns and static columns for future indexing
    t_cols = list(G.columns[2:]) # avoid unique_id and ds
    s_cols = list(S.columns[1:]) # avoid unique_id

    G = G.groupby(['unique_id'])
    S = S.groupby(['unique_id'])

    ts_data = []
    meta_data = []
    for idx, group in G:
        group = group.reset_index(drop=True)
        meta_data.append(group.values[:, :2]) # save unique_id and ds
        ts_data.append(group.values[:, 2:]) # avoid unique_id and ds

    s_data = []
    for idx, group in S:
        s_data.append(group.iloc[:, 1:].values) # avoid unique_id
        assert len(s_data[-1])==1, 'Check repetitions of unique_ids'

    del S, Y, X, M, G
    gc.collect()

    return ts_data, s_data, meta_data, t_cols, s_cols

# Cell
@patch
def _create_tensor(self: TimeSeriesDataset,
                   ts_data: List[Dict[str, np.ndarray]],
                   s_data: List[Dict[str, np.ndarray]]) -> Tuple[np.ndarray,
                                                                 np.ndarray,
                                                                 np.ndarray]:
    """Transforms outputs from self._df_to_lists to numpy arrays.

    Parameters
    ----------
    ts_data: List[Dict[str, np.ndarray]]
        Each element of the list is a dictionary with target, exogenous
        and mask values.
    s_data: List[Dict[str, np.ndarray]]
        Each element of the list is a dictionary with static variables.

    Returns
    -------
    Tuple of three elements:
        - ts_tensor of shape (n_series, n_channels, max_len) n_channels = t_cols + masks
        - s_matrix of shape (n_series, n_s)
        - len_series: numpy array with series lenghts.
    """
    ts_tensor = np.zeros((self.n_series, self.n_channels, self.max_len))

    len_series = []
    for idx, ts_idx in enumerate(ts_data):
        # Left padded time series tensor
        ts_tensor[idx, :, -ts_idx.shape[0]:] = ts_idx.T
        len_series.append(ts_idx.shape[0])

    s_matrix = np.vstack(s_data)
    len_series = np.array(len_series)

    return ts_tensor, s_matrix, len_series

# Cell
@patch
def _get_f_idxs(self: TimeSeriesDataset,
               cols: List[str]) -> List:
    """Gets indexes of exogenous variables.

    Parameters
    ----------
    cols: List[str]
        Interest exogenous variables.

    Returns
    -------
    Indexes of cols variables.
    """
    # Check if cols are available f_cols and return the idxs
    if not all(col in self.f_cols for col in cols):
        str_cols = ', '.join(cols)
        raise Exception(f'Some variables in {str_cols} are not available in f_cols.')

    f_idxs = [self.t_cols.index(col) for col in cols]

    return f_idxs

# Cell
@patch
def _create_windows_tensor(self: TimeSeriesDataset,
                           idx: slice) -> Tuple[t.Tensor, t.Tensor, t.Tensor]:
    """Creates windows of size windows_size from
    the ts_tensor of the TimeSeriesDataset filtered by
    window_sampling_limit and ts_idxs. The step of each window
    is defined by idx_to_sample_freq.

    Parameters
    ----------
    index: slice
        Indexes of time series to consider.

    Returns
    -------
    Tuple of three elements:
        - Windows tensor of shape (windows, channels, input_size + output_size)
        - Static variables tensor of shape (windows * series, n_static)
        - Time Series indexes for each window.
    """
    # Default ts_idxs=ts_idxs sends all the data, otherwise filters series
    tensor = self.ts_tensor[idx, :, self.first_ds:]
    tensor = t.Tensor(tensor)

    padder = t.nn.ConstantPad1d(padding=self.padding, value=0)
    tensor = padder(tensor)

    # Creating rolling windows and 'flattens' them
    windows = tensor.unfold(dimension=-1,
                            size=self.windows_size,
                            step=self.idx_to_sample_freq)
    # n_serie, n_channel, n_time, window_size -> n_serie, n_time, n_channel, window_size
    windows = windows.permute(0, 2, 1, 3)
    windows = windows.reshape(-1, self.n_channels, self.windows_size)

    # Broadcast s_matrix: This works because unfold in windows_tensor, orders: serie, time

    ts_idxs = self.ts_idxs[idx]
    n_ts = len(ts_idxs)
    windows_per_serie = len(windows) / n_ts

    ts_idxs = ts_idxs.repeat(repeats=windows_per_serie)
    s_matrix = self.s_matrix[idx]
    s_matrix = s_matrix.repeat(repeats=windows_per_serie, axis=0)

    s_matrix = t.Tensor(s_matrix)
    ts_idxs = t.as_tensor(ts_idxs, dtype=t.long)

    return windows, s_matrix, ts_idxs

# Cell
@patch
def _get_samplable_windows_idxs(self: TimeSeriesDataset,
                                ts_windows_flatten: t.Tensor) -> np.ndarray:
    """Gets indexes of windows that fulfills conditions.

    Parameters
    ----------
    ts_windows_flatten: t.Tensor
        Tensor of shape (windows, n_channels, windows_size)

    Returns
    -------
    Numpy array of indexes of ts_windows_flatten that
    fulfills conditions.

    Notes
    -----
    [1] If complete_inputs=True
        return all windows which its ouput_size
        has complete sample_mask and its input_size
        has complete available_mask.
    [2] If complete_inputs=False
        returns all windows which its
        output_size has complete sample_mask.
        This avoids leakage.
    [3] If complete_outputs=False
        returns all windows which its
        output_size has complete sample_mask.
        This avoids leakage.
    [4] If complete_outputs=True
        return all windows which its ouput_size
        has complete sample_mask and its output_size
        has complete available_mask.
    """
    sample_condition = ts_windows_flatten[:, self.t_cols.index('sample_mask'), -self.output_size:]
    sample_condition = t.sum(sample_condition, axis=1)
    sample_condition = (sample_condition == self.output_size) * 1
    if self.complete_inputs:
        av_condition_in = ts_windows_flatten[:, self.t_cols.index('available_mask'),
                                                 :-self.output_size]
        av_condition_in = t.sum(av_condition_in, axis=1)
        av_condition_in = (av_condition_in == self.windows_size - self.output_size) * 1
    else:
        av_condition_in = sample_condition

    if self.complete_outputs:
        av_condition_out = ts_windows_flatten[:, self.t_cols.index('available_mask'),
                                              -(self.output_size + 1):]
        av_condition_out = t.sum(av_condition_out, axis=1)
        av_condition_out = (av_condition_out == self.output_size + 1) * 1
    else:
        av_condition_out = sample_condition

    sampling_idx = t.nonzero(av_condition_in * av_condition_out * sample_condition > 0)

    sampling_idx = sampling_idx.flatten().numpy()

    return sampling_idx

# Cell
@patch
def __getitem__(self: TimeSeriesDataset,
                idx: Union[slice, int]) -> Dict[str, t.Tensor]:
    """Creates batch based on index.

    Parameters
    ----------
    index: np.ndarray
        Indexes of time series to consider.

    Returns
    -------
    Dictionary with keys:
        - S
        - Y
        - X
        - available_mask
        - sample_mask
        - idxs
    """
    # Checks for idx
    if isinstance(idx, int):
        idx = [idx]
    elif isinstance(idx, slice) or isinstance(idx, list):
        pass
    else:
        raise Exception('Use slices, int or list for getitem.')

    # Create windows for each sampled ts and sample random unmasked windows from each ts
    windows, s_matrix, ts_idxs = self._create_windows_tensor(idx=idx)
    windows_idxs = self._get_samplable_windows_idxs(ts_windows_flatten=windows)
    if not windows_idxs.size:
        if self.skip_nonsamplable:
            n_ts = len(idx) if isinstance(idx, list) else len(range(*idx.indices(self.n_series)))
            idx = np.random.choice(self.samplable_ts_idxs, size=n_ts).tolist()
            return self[idx]

        raise Exception(
            f'Time Series {idx} are not samplable. '
            'Check the data, masks, window_sampling_limit, '
            'input_size, output_size, masks.'
        )

    # Index the windows and s_matrix tensors of batch
    windows = windows[windows_idxs]
    S = s_matrix[windows_idxs]
    ts_idxs = ts_idxs[windows_idxs]
    if self.last_samplable_window:
        _, idxs_counts = t.unique(ts_idxs, return_counts=True)
        last_idxs = idxs_counts.cumsum(0) - 1
        windows = windows[last_idxs]
        S = s_matrix[last_idxs]
        ts_idxs = ts_idxs[last_idxs]


    # Parse windows to elements of batch
    Y = windows[:, self.t_cols.index('y'), :]
    X = windows[:, (self.t_cols.index('y') + 1):self.t_cols.index('available_mask'), :]
    available_mask = windows[:, self.t_cols.index('available_mask'), :]
    sample_mask = windows[:, self.t_cols.index('sample_mask'), :]

    batch = {'S': S, 'Y': Y, 'X': X,
             'available_mask': available_mask,
             'sample_mask': sample_mask,
             'idxs': ts_idxs}

    return batch

# Cell
@patch
def __len__(self: TimeSeriesDataset):
    return self.n_series

# Cell
@patch
def get_n_variables(self: TimeSeriesDataset) -> Tuple[int, int]:
    """Gets number of exogenous and static variables."""
    return self.n_x, self.n_s

@patch
def get_n_series(self: TimeSeriesDataset) -> int:
    """Gets number of time series."""
    return self.n_series

@patch
def get_max_len(self: TimeSeriesDataset) -> int:
    """Gets max len of time series."""
    return self.max_len

@patch
def get_n_channels(self: TimeSeriesDataset) -> int:
    """Gets number of channels considered."""
    return self.n_channels

@patch
def get_frequency(self: TimeSeriesDataset) -> str:
    """Gets infered frequency."""
    return self.frequency

# Cell
def get_default_mask_df(Y_df: pd.DataFrame,
                        ds_in_test: int,
                        is_test: bool) -> pd.DataFrame:
    """Constructs default mask df.

    Parameters
    ----------
    Y_df: pd.DataFrame
        Target time series with columns ['unique_id', 'ds', 'y'].
    ds_in_test: int
        Numer of datestamps to use as outsample.
    is_test: bool
        Wheter target time series belongs to test set.

    Returns
    -------
    Mask DataFrame with columns
    ['unique_id', 'ds', 'available_mask', 'sample_mask'].
    """
    mask_df = Y_df[['unique_id', 'ds']].copy()
    mask_df['available_mask'] = 1
    mask_df['sample_mask'] = 1
    mask_df = mask_df.set_index(['unique_id', 'ds'])

    mask_df_s = mask_df.sort_values(by=['unique_id', 'ds'])
    zero_idx = mask_df_s.groupby('unique_id').tail(ds_in_test).index
    mask_df.loc[zero_idx, 'sample_mask'] = 0
    mask_df = mask_df.reset_index()
    mask_df.index = Y_df.index

    assert len(mask_df)==len(Y_df), \
        f'The mask_df length {len(mask_df)} is not equal to Y_df length {len(Y_df)}'

    if is_test:
        mask_df['sample_mask'] = 1 - mask_df['sample_mask']

    return mask_df