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

"""Tests for MADE."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import edward2 as ed
import numpy as np
import tensorflow.compat.v1 as tf1
import tensorflow.compat.v2 as tf

from tensorflow.python.framework import test_util  # pylint: disable=g-direct-tensorflow-import


@test_util.run_all_in_graph_and_eager_modes
class MADETest(tf.test.TestCase):

  def testMADELeftToRight(self):
    np.random.seed(83243)
    batch_size = 2
    length = 3
    channels = 1
    units = 5
    network = ed.layers.MADE(units, [4], activation=tf.nn.relu)
    inputs = tf.zeros([batch_size, length, channels])
    outputs = network(inputs)

    num_weights = sum([np.prod(weight.shape) for weight in network.weights])
    # Disable lint error for open-source. pylint: disable=g-generic-assert
    self.assertEqual(len(network.weights), 4)
    # pylint: enable=g-generic-assert
    self.assertEqual(num_weights, (3*1*4 + 4) + (4*3*5 + 3*5))

    self.evaluate(tf1.global_variables_initializer())
    outputs_val = self.evaluate(outputs)
    self.assertAllEqual(outputs_val[:, 0, :], np.zeros((batch_size, units)))
    self.assertEqual(outputs_val.shape, (batch_size, length, units))

  def testMADERightToLeft(self):
    np.random.seed(1328)
    batch_size = 2
    length = 3
    channels = 5
    units = 1
    network = ed.layers.MADE(units, [4, 3],
                             input_order='right-to-left',
                             activation=tf.nn.relu,
                             use_bias=False)
    inputs = tf.zeros([batch_size, length, channels])
    outputs = network(inputs)

    num_weights = sum([np.prod(weight.shape) for weight in network.weights])
    # Disable lint error for open-source. pylint: disable=g-generic-assert
    self.assertEqual(len(network.weights), 3)
    # pylint: enable=g-generic-assert
    self.assertEqual(num_weights, 3*5*4 + 4*3 + 3*3*1)

    self.evaluate(tf1.global_variables_initializer())
    outputs_val = self.evaluate(outputs)
    self.assertAllEqual(outputs_val[:, -1, :], np.zeros((batch_size, units)))
    self.assertEqual(outputs_val.shape, (batch_size, length, units))

  def testMADENoHidden(self):
    np.random.seed(532)
    batch_size = 2
    length = 3
    channels = 5
    units = 4
    network = ed.layers.MADE(units, [], input_order='left-to-right')
    inputs = tf.zeros([batch_size, length, channels])
    outputs = network(inputs)

    num_weights = sum([np.prod(weight.shape) for weight in network.weights])
    # Disable lint error for open-source. pylint: disable=g-generic-assert
    self.assertEqual(len(network.weights), 2)
    # pylint: enable=g-generic-assert
    self.assertEqual(num_weights, 3*5*3*4 + 3*4)

    self.evaluate(tf1.global_variables_initializer())
    outputs_val = self.evaluate(outputs)
    self.assertAllEqual(outputs_val[:, 0, :], np.zeros((batch_size, units)))
    self.assertEqual(outputs_val.shape, (batch_size, length, units))


if __name__ == '__main__':
  tf.test.main()
