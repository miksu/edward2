# coding=utf-8
# Copyright 2019 The Edward2 Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Masked autoencoder for distribution estimation."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow.compat.v1 as tf1
import tensorflow.compat.v2 as tf


class MADE(tf.keras.Model):
  """Masked autoencoder for distribution estimation (Germain et al., 2015).

  MADE takes as input a real Tensor of shape [..., length, channels] and returns
  a Tensor of shape [..., length, units] and same dtype. It masks layer weights
  to satisfy autoregressive constraints with respect to the length dimension. In
  particular, for a given ordering, each input dimension of length can be
  reconstructed from previous dimensions.

  The output's units dimension captures per-time-step representations. For
  example, setting units to 2 can parameterize the location and log-scale of an
  autoregressive Gaussian distribution.
  """

  def __init__(self,
               units,
               hidden_dims,
               input_order='left-to-right',
               hidden_order='left-to-right',
               activation=None,
               use_bias=True,
               **kwargs):
    """Constructs network.

    Args:
      units: Positive integer, dimensionality of the output space.
      hidden_dims: list with the number of hidden units per layer. It does not
        include the output layer; those number of units will always be set to
        the input dimension multiplied by `num_heads`. Each hidden unit size
        must be at least the size of length (otherwise autoregressivity is not
        possible).
      input_order: Order of degrees to the input units: 'random',
        'left-to-right', 'right-to-left', or an array of an explicit order.
        For example, 'left-to-right' builds an autoregressive model
        p(x) = p(x1) p(x2 | x1) ... p(xD | x<D).
      hidden_order: Order of degrees to the hidden units: 'random',
        'left-to-right'. If 'left-to-right', hidden units are allocated equally
        (up to a remainder term) to each degree.
      activation: Activation function.
      use_bias: Whether to use a bias.
      **kwargs: Keyword arguments of parent class.
    """
    super(MADE, self).__init__(**kwargs)
    self.units = int(units)
    self.hidden_dims = hidden_dims
    self.input_order = input_order
    self.hidden_order = hidden_order
    self.activation = tf.keras.activations.get(activation)
    self.use_bias = use_bias
    self.network = tf.keras.Sequential([])

  def build(self, input_shape):
    input_shape = tf.TensorShape(input_shape)
    length = input_shape[-2]
    channels = input_shape[-1]
    if isinstance(length, tf1.Dimension):
      length = length.value
    if isinstance(channels, tf1.Dimension):
      channels = channels.value
    if length is None or channels is None:
      raise ValueError('The two last dimensions of the inputs to '
                       '`MADE` should be defined. Found `None`.')
    masks = create_masks(input_dim=length,
                         hidden_dims=self.hidden_dims,
                         input_order=self.input_order,
                         hidden_order=self.hidden_order)

    # Input-to-hidden layer: [..., length, channels] -> [..., hidden_dims[0]].
    self.network.add(tf.keras.layers.Reshape([length * channels]))
    # Tile the mask so each element repeats contiguously; this is compatible
    # with the autoregressive contraints unlike naive tiling.
    mask = masks[0]
    mask = tf.tile(mask[:, tf.newaxis, :], [1, channels, 1])
    mask = tf.reshape(mask, [mask.shape[0] * channels, mask.shape[-1]])
    if self.hidden_dims:
      layer = tf.keras.layers.Dense(
          self.hidden_dims[0],
          kernel_initializer=make_masked_initializer(mask),
          kernel_constraint=make_masked_constraint(mask),
          activation=self.activation,
          use_bias=self.use_bias)
      self.network.add(layer)

    # Hidden-to-hidden layers: [..., hidden_dims[l-1]] -> [..., hidden_dims[l]].
    for l in range(1, len(self.hidden_dims)):
      layer = tf.keras.layers.Dense(
          self.hidden_dims[l],
          kernel_initializer=make_masked_initializer(masks[l]),
          kernel_constraint=make_masked_constraint(masks[l]),
          activation=self.activation,
          use_bias=self.use_bias)
      self.network.add(layer)

    # Hidden-to-output layer: [..., hidden_dims[-1]] -> [..., length, units].
    # Tile the mask so each element repeats contiguously; this is compatible
    # with the autoregressive contraints unlike naive tiling.
    if self.hidden_dims:
      mask = masks[-1]
    mask = tf.tile(mask[..., tf.newaxis], [1, 1, self.units])
    mask = tf.reshape(mask, [mask.shape[0], mask.shape[1] * self.units])
    layer = tf.keras.layers.Dense(
        length * self.units,
        kernel_initializer=make_masked_initializer(mask),
        kernel_constraint=make_masked_constraint(mask),
        activation=None,
        use_bias=self.use_bias)
    self.network.add(layer)
    self.network.add(tf.keras.layers.Reshape([length, self.units]))
    self.built = True

  def call(self, inputs):
    return self.network(inputs)


def create_degrees(input_dim,
                   hidden_dims,
                   input_order='left-to-right',
                   hidden_order='left-to-right'):
  """Returns a list of degree vectors, one for each input and hidden layer.

  A unit with degree d can only receive input from units with degree < d. Output
  units always have the same degree as their associated input unit.

  Args:
    input_dim: Number of inputs.
    hidden_dims: list with the number of hidden units per layer. It does not
      include the output layer. Each hidden unit size must be at least the size
      of length (otherwise autoregressivity is not possible).
    input_order: Order of degrees to the input units: 'random', 'left-to-right',
      'right-to-left', or an array of an explicit order. For example,
      'left-to-right' builds an autoregressive model
      p(x) = p(x1) p(x2 | x1) ... p(xD | x<D).
    hidden_order: Order of degrees to the hidden units: 'random',
      'left-to-right'. If 'left-to-right', hidden units are allocated equally
      (up to a remainder term) to each degree.
  """
  if (isinstance(input_order, str) and
      input_order not in ('random', 'left-to-right', 'right-to-left')):
    raise ValueError('Input order is not valid.')
  if hidden_order not in ('random', 'left-to-right'):
    raise ValueError('Hidden order is not valid.')

  degrees = []
  if isinstance(input_order, str):
    input_degrees = np.arange(1, input_dim + 1)
    if input_order == 'right-to-left':
      input_degrees = np.flip(input_degrees, 0)
    elif input_order == 'random':
      np.random.shuffle(input_degrees)
  else:
    input_order = np.array(input_order)
    if np.all(np.sort(input_order) != np.arange(1, input_dim + 1)):
      raise ValueError('invalid input order')
    input_degrees = input_order
  degrees.append(input_degrees)

  for units in hidden_dims:
    if hidden_order == 'random':
      min_prev_degree = min(np.min(degrees[-1]), input_dim - 1)
      hidden_degrees = np.random.randint(
          low=min_prev_degree, high=input_dim, size=units)
    elif hidden_order == 'left-to-right':
      hidden_degrees = (np.arange(units) % max(1, input_dim - 1) +
                        min(1, input_dim - 1))
    degrees.append(hidden_degrees)
  return degrees


def create_masks(input_dim,
                 hidden_dims,
                 input_order='left-to-right',
                 hidden_order='left-to-right'):
  """Returns a list of binary mask matrices respecting autoregressive ordering.

  Args:
    input_dim: Number of inputs.
    hidden_dims: list with the number of hidden units per layer. It does not
      include the output layer; those number of units will always be set to
      input_dim downstream. Each hidden unit size must be at least the size of
      length (otherwise autoregressivity is not possible).
    input_order: Order of degrees to the input units: 'random', 'left-to-right',
      'right-to-left', or an array of an explicit order. For example,
      'left-to-right' builds an autoregressive model
      p(x) = p(x1) p(x2 | x1) ... p(xD | x<D).
    hidden_order: Order of degrees to the hidden units: 'random',
      'left-to-right'. If 'left-to-right', hidden units are allocated equally
      (up to a remainder term) to each degree.
  """
  degrees = create_degrees(input_dim, hidden_dims, input_order, hidden_order)
  masks = []
  # Create input-to-hidden and hidden-to-hidden masks.
  for input_degrees, output_degrees in zip(degrees[:-1], degrees[1:]):
    mask = tf.cast(input_degrees[:, np.newaxis] <= output_degrees, tf.float32)
    masks.append(mask)

  # Create hidden-to-output mask.
  mask = tf.cast(degrees[-1][:, np.newaxis] < degrees[0], tf.float32)
  masks.append(mask)
  return masks


def make_masked_initializer(mask):
  initializer = tf.keras.initializers.GlorotUniform()
  def masked_initializer(shape, dtype=None):
    return mask * initializer(shape, dtype)
  return masked_initializer


def make_masked_constraint(mask):
  constraint = tf.identity
  def masked_constraint(x):
    return mask * constraint(x)
  return masked_constraint
