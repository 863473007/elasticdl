import tensorflow as tf
from tensorflow.python.framework.ops import EagerTensor
import numpy as np


class MnistModel(tf.keras.Model):
    def __init__(self, channel_last=True):
        super(MnistModel, self).__init__(name='mnist_model')

        self._inputs = tf.keras.layers.Input(shape=(32, 32, 3), name="image")

        use_bias = True
        self._conv_1 = tf.keras.layers.Conv2D(32,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_1 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_1 = tf.keras.layers.Activation(tf.nn.relu)

        self._conv_2 = tf.keras.layers.Conv2D(32,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_2 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_2 = tf.keras.layers.Activation(tf.nn.relu)

        self._max_pool_1 = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
        self._dropout_1 = tf.keras.layers.Dropout(0.2)

        self._conv_3 = tf.keras.layers.Conv2D(64,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_3 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_3 = tf.keras.layers.Activation(tf.nn.relu)

        self._conv_4 = tf.keras.layers.Conv2D(64,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_4 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_4 = tf.keras.layers.Activation(tf.nn.relu)

        self._max_pool_2 = tf.keras.layers.MaxPooling2D()
        self._dropout_2 = tf.keras.layers.Dropout(0.3)

        self._conv_5 = tf.keras.layers.Conv2D(128,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_5 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_5 = tf.keras.layers.Activation(tf.nn.relu)

        self._conv_6 = tf.keras.layers.Conv2D(128,
            kernel_size=(3, 3),
            padding='same',
            use_bias=use_bias,
            activation=None)
        self._bn_6 = tf.keras.layers.BatchNormalization(epsilon=1e-06, axis=-1, momentum=0.9)
        self._relu_6 = tf.keras.layers.Activation(tf.nn.relu)

        self._max_pool_3 = tf.keras.layers.MaxPooling2D()
        self._dropout_3 = tf.keras.layers.Dropout(0.4)

        self._flatten_1 = tf.keras.layers.Flatten()
        self._dense_1 = tf.keras.layers.Dense(10, activation=tf.nn.softmax, name='output')

    def call(self, inputs, training=False):
        x = self._inputs(inputs)
        x = self._conv_1(x)
        x = self._bn_1(x)
        x = self._relu_1(x)
        x = self._conv_2(x)
        x = self._bn_2(x)
        x = self._relu_2(x)
        x = self._max_pool_1(x)
        x = self._dropout_1(x)
        x = self._conv_3(x)
        x = self._bn_3(x)
        x = self._relu_3(x)
        x = self._conv_4(x)
        x = self._bn_4(x)
        x = self._relu_4(x)
        x = self._max_pool_2(x)
        x = self._dropout_2(x)
        x = self._conv_5(x)
        x = self._bn_5(x)
        x = self._relu_5(x)
        x = self._conv_6 (x)
        x = self._bn_6(x)
        x = self._relu_6(x)
        x = self._max_pool_3(x)
        x = self._dropout_3(x)
        x = self._flatten_1(x)
        x = self._dense_1(x)

model = MnistModel()

def feature_columns():
    return [tf.feature_column.numeric_column(key="image",
        dtype=tf.dtypes.float32, shape=[3, 32, 32])]

def label_columns():
    return [tf.feature_column.numeric_column(key="label",
        dtype=tf.dtypes.int64, shape=[1, 1])]
        
def loss(output, labels):
    return tf.reduce_mean(
        tf.nn.sparse_softmax_cross_entropy_with_logits(
            logits=output, labels=labels))

def optimizer(lr=0.1):
    return tf.train.GradientDescentOptimizer(lr)

def input_fn(records):
    image_list = []
    label_list = []
    # deserialize
    for r in records:
        get_np_val = (lambda data: data.numpy() if isinstance(data, EagerTensor) else data)
        label = get_np_val(r['label'])
        image = np.frombuffer(get_np_val(r['image']), dtype="float32")
        image = np.resize(image, new_shape=(3, 32, 32))
        image = image.astype(np.float32)
        image /= 255
        label = label.astype(np.int32)
        image_list.append(image)
        label_list.append(label)

    # batching
    batch_size = len(image_list)
    images = np.concatenate(image_list, axis=0)
    images = np.reshape(images, (batch_size, 32, 32, 3))
    labels = np.array(label_list)
    return ({'image': images}, labels)