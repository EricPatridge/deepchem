"""
Contains an abstract base class that supports different ML models.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import sys
import numpy as np
import pandas as pd
import joblib
import os
from deepchem.utils.dataset import NumpyDataset
from deepchem.utils.dataset import load_sharded_dataset
from deepchem.utils.dataset import save_sharded_dataset

class Model(object):
  """
  Abstract base class for different ML models.
  """
  # List of registered models
  registered_model_types = {}
  def __init__(self, model_type, task_types, model_params,
               initialize_raw_model=True):
    self.model_type = model_type
    self.task_types = task_types
    self.model_params = model_params

  def fit_on_batch(self, X, y, w):
    """
    Updates existing model with new information.
    """
    raise NotImplementedError(
        "Each model is responsible for its own fit_on_batch method.")

  def predict_on_batch(self, X):
    """
    Makes predictions on given batch of new data.
    """
    raise NotImplementedError(
        "Each model is responsible for its own predict_on_batch method.")    

  def set_raw_model(self, raw_model):
    """
    Set underlying raw model. Useful when loading from disk.
    """
    self.raw_model = raw_model

  def get_raw_model(self):
    """
    Return raw model.
    """
    return(self.raw_model)

  def get_param_filename(self, out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model_params.joblib")

  def get_model_filename(self, out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model.joblib")

  @staticmethod
  def model_builder(model_type, task_types, model_params,
                    initialize_raw_model=True):
    """
    Factory method that initializes model of requested type.
    """
    if model_type in Model.registered_model_types:
      model = Model.registered_model_types[model_type](
          model_type, task_types, model_params, initialize_raw_model)
    else:
      raise ValueError("model_type %s is not supported" % model_type)
    return model

  @staticmethod
  def register_model_type(model_type, model_class):
    """
    Registers model types in static variable for factory/dispatchers to use.
    """
    Model.registered_model_types[model_type] = model_class

  def load(self, model_dir):
    """Dispatcher function for loading."""
    params = load_sharded_dataset(self.get_model_filename(model_dir))
    self.model_params = params["model_params"]
    self.task_types = params["task_types"]
    self.model_type = params["model_type"]

  def save(self, out_dir):
    """Dispatcher function for saving."""
    params = {"model_params" : self.model_params,
              "task_types" : self.task_types,
              "model_type": self.model_type}
    save_sharded_dataset(params, self.get_params_filename(out_dir))

  def fit(self, numpy_dataset):
    """
    Fits a model on data in a NumpyDataset object.
    """
    # TODO(rbharath/enf): This GPU_RAM is black magic. Needs to be removed/made
    # more general.
    MAX_GPU_RAM = float(691007488/50)
    for (X, y, w, _) in numpy_dataset.itershards():
      if sys.getsizeof(X) > MAX_GPU_RAM:
        nb_block = float(sys.getsizeof(X))/MAX_GPU_RAM
        nb_sample = np.shape(X)[0]
        interval_points = np.linspace(0,nb_sample,nb_block+1).astype(int)
        for j in range(0,len(interval_points)-1):
          indices = range(interval_points[j],interval_points[j+1])
          X_batch = X[indices,:]
          y_batch = y[indices]
          w_batch = w[indices]
          self.fit_on_batch(X_batch, y_batch, w_batch)
      else:
        self.fit_on_batch(X, y, w)

  # TODO(rbharath): What does this function do when y is not provided. Suspect
  # it breaks. Need to fix.

  # TODO(rbharath): The structure of the produced df might be
  # complicated. Better way to model?
  def predict(self, numpy_dataset):
    """
    Uses self to make predictions on provided NumpyDataset object.
    """
    task_names = numpy_dataset.get_task_names()
    pred_task_names = ["%s_pred" % task_name for task_name in task_names]
    w_task_names = ["%s_weight" % task_name for task_name in task_names]
    column_names = (['ids'] + task_names + pred_task_names + w_task_names
                           + ["y_means", "y_stds"])
    pred_y_df = pd.DataFrame(columns=column_names)

    # TODO(rbharath/enf): This is only for GPU models, and is currently depends
    # on magic numbers.
    MAX_GPU_RAM = float(691007488/50)
    for (X, y, w, ids) in numpy_dataset.itershards():
      if sys.getsizeof(X) > MAX_GPU_RAM:
        nb_block = float(sys.getsizeof(X))/MAX_GPU_RAM
        nb_sample = np.shape(X)[0]
        interval_points = np.linspace(0,nb_sample,nb_block+1).astype(int)
        y_preds = []
        for j in range(0,len(interval_points)-1):
          indices = range(interval_points[j],interval_points[j+1])
          y_preds.append(self.predict_on_batch(X[indices,:]))
        y_pred = np.concatenate(y_preds)
      else:
        y_pred = self.predict_on_batch(X)
      y_pred = np.reshape(y_pred, np.shape(y))

      shard_df = pd.DataFrame(columns=column_names)
      shard_df['ids'] = ids
      shard_df[task_names] = y
      shard_df[pred_task_names] = y_pred
      shard_df[w_task_names] = w
      shard_df["y_means"] = numpy_dataset.get_label_means() 
      shard_df["y_stds"] = numpy_dataset.get_label_stds() 
      pred_y_df = pd.concat([pred_y_df, shard_df])

    return pred_y_df 
