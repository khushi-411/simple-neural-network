import sys
import typing

import torch
from torch import Tensor

import knets as nn


class _BaseLayer:
    def __init__(
            self
    ):
        self.order = None
        self.name = None
        self._x = None
        self.data_vars = {}

    def forward(
            self,
            x,
    ):
        raise NotImplementedError

    def backward(
            self
    ):
        raise NotImplementedError

    def _process_input(
            self,
            x,
    ):
        if isinstance(x, Tensor):
            # https://discuss.pytorch.org/t/how-to-cast-a-tensor-to-another-type/2713
            x = x.to(torch.float32)
            x = nn.Variable(x)
            x.info["new_layer_order"] = 0

        self.data_vars["in"] = x
        # x is Variable, extract _x value from x.data
        self.order = x.info["new_layer_order"]
        _x = x.data
        return _x

    def _wrap_out(
            self,
            out,
    ):
        out = nn.Variable(out)
        out.info["new_layer_order"] = self.order + 1
        self.data_vars["out"] = out     # add to layer's data_vars
        return out

    def __call__(
            self,
            x,
    ):
        return self.forward(x)

class ParamLayer(_BaseLayer):
    def __init__(
            self,
            w_shape,
            activation,
            w_initializer,
            b_initializer,
            use_bias
    ):
        super().__init__()
        self.param_vars = {}
        self.w = torch.empty(w_shape, dtype=torch.float32)
        self.param_vars["w"] = self.w
        if use_bias:
            shape = [1]*len(w_shape)
            shape[-1] = w_shape[-1]     # only have bias on the last dimension
            self.b = torch.empty(shape, dtype=torch.float32)
            self.param_vars["b"] = self.b
        self.use_bias = use_bias

        if activation is None:
            self._a = nn.act.Linear()
        elif isinstance(activation, nn.act.Activation):
            self._a = activation
        else:
            raise TypeError

        if w_initializer is None:
            nn.init.TruncatedNormal(0., 0.01).initialize(self.w)
        elif isinstance(w_initializer, nn.init._BaseInitializer):
            w_initializer.initialize(self.w)
        else:
            raise TypeError

        if use_bias:
            if b_initializer is None:
                nn.init.Constant(0.01).initialize(self.b)
            elif isinstance(b_initializer, nn.init._BaseInitializer):
                b_initializer.initialize(self.b)
            else:
                raise TypeError

        self._wx_b = None
        self._activated = None

    def forward(self, x):
        raise NotImplementedError

    def backward(self):
        raise NotImplementedError

class Dense(ParamLayer):
    def __init__(
            self,
            n_in: int,
            n_out: int,
            activation=None,  # activations.Tanh
            w_initializer=None, # initializers.RandomUniform
            b_initializer=None,  # initializers.Constant
            use_bias: bool = True,
    ):
        super().__init__(
            w_shape=(n_in, n_out),
            activation=activation,
            w_initializer=w_initializer,
            b_initializer=b_initializer,
            use_bias=use_bias
        )

        self._n_in = n_in
        self._n_out = n_out

    def forward(
            self,
            x,
    ):
        self._x = self._process_input(x)
        # https://stackoverflow.com/questions/66720543/pytorch-1d-tensors-expected-but-got-2d-tensors
        self._wx_b = self._x.matmul(self.w)
        if self.use_bias:
            self._wx_b += self.b

        self._activated = self._a(self._wx_b)   # if act is None, act will be Linear
        wrapped_out = self._wrap_out(self._activated)
        return wrapped_out

    def backward(
            self
    ):
        # dw, db
        dz = self.data_vars["out"].error
        dz *= self._a.derivative(self._wx_b)
        grads = {"w": self._x.T.matmul(dz)}
        if self.use_bias:
            grads["b"] = torch.sum(dz, axis=0, keepdims=True)
        # dx
        self.data_vars["in"].set_error(dz.matmul(self.w.T))     # pass error to the layer before
        return grads
