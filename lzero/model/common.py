"""
Overview:
    In this Python file, we provide a collection of reusable model templates designed to streamline the development
    process for various custom algorithms. By utilizing these pre-built model templates, users can quickly adapt and
    customize their custom algorithms, ensuring efficient and effective development.
    BTW, users can refer to the unittest of these model templates to learn how to use them.
"""
import math
from typing import Optional, Tuple, List
from dataclasses import dataclass
import numpy as np
import torch
import torch.nn as nn
from ding.torch_utils import MLP, ResBlock
from ding.utils import SequenceType


# use dataclass to make the output of network more convenient to use
@dataclass
class EZNetworkOutput:
    # output format of the EfficientZero model
    value: torch.Tensor
    value_prefix: torch.Tensor
    policy_logits: torch.Tensor
    latent_state: torch.Tensor
    reward_hidden_state: Tuple[torch.Tensor]

#daev
@dataclass
class MZNetworkOutput:
    # output format of the MuZero model
    value: torch.Tensor
    reward: torch.Tensor
    policy_logits: torch.Tensor
    latent_state: torch.Tensor
    reconstruction: torch.Tensor

class DownSample(nn.Module):
            
    def __init__(self, observation_shape: SequenceType, out_channels: int, activation: nn.Module = nn.ReLU(inplace=True),
                 norm_type: Optional[str] = 'BN',
                 ) -> None:
        """
        Overview:
            Define downSample convolution network. Encode the observation into hidden state.
            This network is often used in video games like Atari. In board games like go and chess,
            we don't need this module.
        Arguments:
            - observation_shape (:obj:`SequenceType`): The shape of observation space, e.g. [C, W, H]=[12, 96, 96]
                for video games like atari, RGB 3 channel times stack 4 frames.
            - out_channels (:obj:`int`): The output channels of output hidden state.
            - activation (:obj:`nn.Module`): The activation function used in network, defaults to nn.ReLU(). \
                Use the inplace operation to speed up.
            - norm_type (:obj:`Optional[str]`): The normalization type used in network, defaults to 'BN'. 
        """
        super().__init__()
        assert norm_type in ['BN', 'LN'], "norm_type must in ['BN', 'LN']"

        self.conv1 = nn.Conv2d(
            observation_shape[0],
            out_channels // 2,
            kernel_size=3,
            stride=2,
            padding=1,
            bias=False,  # disable bias for better convergence
        )
        if norm_type == 'BN':
            self.norm1 = nn.BatchNorm2d(out_channels // 2)
        elif norm_type == 'LN':
            self.norm1 = nn.LayerNorm([out_channels // 2, observation_shape[-2] // 2, observation_shape[-1] // 2])

        self.resblocks1 = nn.ModuleList(
            [
                ResBlock(
                    in_channels=out_channels // 2,
                    activation=activation,
                    norm_type='BN',
                    res_type='basic',
                    bias=False
                ) for _ in range(1)
            ]
        )
        self.downsample_block = ResBlock(
            in_channels=out_channels // 2,
            out_channels=out_channels,
            activation=activation,
            norm_type='BN',
            res_type='downsample',
            bias=False
        )
        self.resblocks2 = nn.ModuleList(
            [
                ResBlock(
                    in_channels=out_channels, activation=activation, norm_type='BN', res_type='basic', bias=False
                ) for _ in range(1)
            ]
        )
        self.pooling1 = nn.AvgPool2d(kernel_size=3, stride=2, padding=1)
        self.resblocks3 = nn.ModuleList(
            [
                ResBlock(
                    in_channels=out_channels, activation=activation, norm_type='BN', res_type='basic', bias=False
                ) for _ in range(1)
            ]
        )
        self.pooling2 = nn.AvgPool2d(kernel_size=3, stride=2, padding=1)
        self.activation = activation

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Shapes:
            - x (:obj:`torch.Tensor`): :math:`(B, C_in, W, H)`, where B is batch size, C_in is channel, W is width, \
                H is height.
            - output (:obj:`torch.Tensor`): :math:`(B, C_out, W_, H_)`, where B is batch size, C_out is channel, W_ is \
                output width, H_ is output height.
        """
        x = self.conv1(x)
        x = self.norm1(x)
        x = self.activation(x)

        for block in self.resblocks1:
            x = block(x)
        x = self.downsample_block(x)
        for block in self.resblocks2:
            x = block(x)
        x = self.pooling1(x)
        for block in self.resblocks3:
            x = block(x)
        output = self.pooling2(x)
        return output
    



class RepresentationNetwork(nn.Module):

    def __init__(
            self,
            observation_shape: SequenceType = (12, 96, 96),
            num_res_blocks: int = 1,
            num_channels: int = 64,
            downsample: bool = True,
            activation: nn.Module = nn.ReLU(inplace=True),
            norm_type: str = 'BN',
    ) -> None:
        """
        Overview:
            Representation network used in MuZero and derived algorithms. Encode the 2D image obs into hidden state.
        Arguments:
            - observation_shape (:obj:`SequenceType`): The shape of observation space, e.g. [C, W, H]=[12, 96, 96]
                for video games like atari, RGB 3 channel times stack 4 frames.
            - num_res_blocks (:obj:`int`): The number of residual blocks.
            - num_channels (:obj:`int`): The channel of output hidden state.
            - downsample (:obj:`bool`): Whether to do downsampling for observations in ``representation_network``, \
                defaults to True. This option is often used in video games like Atari. In board games like go, \
                we don't need this module.
            - activation (:obj:`nn.Module`): The activation function used in network, defaults to nn.ReLU(). \
                Use the inplace operation to speed up.
            - norm_type (:obj:`str`): The type of normalization in networks. defaults to 'BN'.
        """
        super().__init__()
        assert norm_type in ['BN', 'LN'], "norm_type must in ['BN', 'LN']"

        self.downsample = downsample
        if self.downsample:
            self.downsample_net = DownSample(
                observation_shape,
                num_channels,
                activation=activation,
                norm_type=norm_type,
            )
        else:
            self.conv = nn.Conv2d(observation_shape[0], num_channels, kernel_size=3, stride=1, padding=1, bias=False)

            if norm_type == 'BN':
                self.norm = nn.BatchNorm2d(num_channels)
            elif norm_type == 'LN':
                if downsample:
                    self.norm = nn.LayerNorm([num_channels, math.ceil(observation_shape[-2] / 16), math.ceil(observation_shape[-1] / 16)])
                else:
                    self.norm = nn.LayerNorm([num_channels, observation_shape[-2], observation_shape[-1]])
            
        self.resblocks = nn.ModuleList(
            [
                ResBlock(
                    in_channels=num_channels, activation=activation, norm_type='BN', res_type='basic', bias=False
                ) for _ in range(num_res_blocks)
            ]
        )
        self.activation = activation

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Shapes:
            - x (:obj:`torch.Tensor`): :math:`(B, C_in, W, H)`, where B is batch size, C_in is channel, W is width, \
                H is height.
            - output (:obj:`torch.Tensor`): :math:`(B, C_out, W_, H_)`, where B is batch size, C_out is channel, W_ is \
                output width, H_ is output height.
        """
        if self.downsample:
            x = self.downsample_net(x)
        else:
            x = self.conv(x)
            x = self.norm(x)
            x = self.activation(x)

        for block in self.resblocks:
            x = block(x)
        return x

    def get_param_mean(self) -> float:
        """
        Overview:
            Get the mean of parameters in the network for debug and visualization.
        Returns:
            - mean (:obj:`float`): The mean of parameters in the network.
        """
        mean = []
        for name, param in self.named_parameters():
            mean += np.abs(param.detach().cpu().numpy().reshape(-1)).tolist()
        mean = sum(mean) / len(mean)
        return mean


class RepresentationNetworkMLP(nn.Module):

    def __init__(
            self,
            observation_shape: int,
            hidden_channels: int = 64,
            layer_num: int = 2,
            activation: Optional[nn.Module] = nn.ReLU(inplace=True),
            last_linear_layer_init_zero: bool = True,
            norm_type: Optional[str] = 'BN',
    ) -> torch.Tensor:
        """
        Overview:
            Representation network used in MuZero and derived algorithms. Encode the vector obs into latent state \
                with Multi-Layer Perceptron (MLP).
        Arguments:
            - observation_shape (:obj:`int`): The shape of vector observation space, e.g. N = 10.
            - num_res_blocks (:obj:`int`): The number of residual blocks.
            - hidden_channels (:obj:`int`): The channel of output hidden state.
            - downsample (:obj:`bool`): Whether to do downsampling for observations in ``representation_network``, \
                defaults to True. This option is often used in video games like Atari. In board games like go, \
                we don't need this module.
            - activation (:obj:`nn.Module`): The activation function used in network, defaults to nn.ReLU(). \
                Use the inplace operation to speed up.
            - last_linear_layer_init_zero (:obj:`bool`): Whether to initialize the last linear layer with zeros, \
                which can provide stable zero outputs in the beginning, defaults to True.
            - norm_type (:obj:`str`): The type of normalization in networks. defaults to 'BN'.
        """
        super().__init__()
        self.fc_representation = MLP(
            in_channels=observation_shape,
            hidden_channels=hidden_channels,
            out_channels=hidden_channels,
            layer_num=layer_num,
            activation=activation,
            norm_type=norm_type,
            # don't use activation and norm in the last layer of representation network is important for convergence.
            output_activation=False,
            output_norm=False,
            # last_linear_layer_init_zero=True is beneficial for convergence speed.
            last_linear_layer_init_zero=True,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Shapes:
            - x (:obj:`torch.Tensor`): :math:`(B, N)`, where B is batch size, N is the length of vector observation.
            - output (:obj:`torch.Tensor`): :math:`(B, hidden_channels)`, where B is batch size.
        """
        return self.fc_representation(x)


class PredictionNetwork(nn.Module):

    def __init__(
            self,
            observation_shape: SequenceType,
            action_space_size: int,
            num_res_blocks: int,
            num_channels: int,
            value_head_channels: int,
            policy_head_channels: int,
            fc_value_layers: int,
            fc_policy_layers: int,
            output_support_size: int,
            flatten_output_size_for_value_head: int,
            flatten_output_size_for_policy_head: int,
            downsample: bool = False,
            last_linear_layer_init_zero: bool = True,
            activation: nn.Module = nn.ReLU(inplace=True),
            norm_type: Optional[str] = 'BN',
    ) -> None:
        """
        Overview:
            The definition of policy and value prediction network, which is used to predict value and policy by the
            given latent state.
        Arguments:
            - observation_shape (:obj:`SequenceType`): The shape of observation space, e.g. (C, H, W) for image.
            - action_space_size: (:obj:`int`): Action space size, usually an integer number for discrete action space.
            - num_res_blocks (:obj:`int`): The number of res blocks in AlphaZero model.
            - num_channels (:obj:`int`): The channels of hidden states.
            - value_head_channels (:obj:`int`): The channels of value head.
            - policy_head_channels (:obj:`int`): The channels of policy head.
            - fc_value_layers (:obj:`SequenceType`): The number of hidden layers used in value head (MLP head).
            - fc_policy_layers (:obj:`SequenceType`): The number of hidden layers used in policy head (MLP head).
            - output_support_size (:obj:`int`): The size of categorical value output.
            - self_supervised_learning_loss (:obj:`bool`): Whether to use self_supervised_learning related networks \
            - flatten_output_size_for_value_head (:obj:`int`): The size of flatten hidden states, i.e. the input size \
                of the value head.
            - flatten_output_size_for_policy_head (:obj:`int`): The size of flatten hidden states, i.e. the input size \
                of the policy head.
            - downsample (:obj:`bool`): Whether to do downsampling for observations in ``representation_network``.
            - last_linear_layer_init_zero (:obj:`bool`): Whether to use zero initializations for the last layer of \
                dynamics/prediction mlp, default sets it to True.
            - activation (:obj:`Optional[nn.Module]`): Activation function used in network, which often use in-place \
                operation to speedup, e.g. ReLU(inplace=True).
            - norm_type (:obj:`str`): The type of normalization in networks. defaults to 'BN'.
        """
        super(PredictionNetwork, self).__init__()
        assert norm_type in ['BN', 'LN'], "norm_type must in ['BN', 'LN']"

        self.resblocks = nn.ModuleList(
            [
                ResBlock(
                    in_channels=num_channels, activation=activation, norm_type='BN', res_type='basic', bias=False
                ) for _ in range(num_res_blocks)
            ]
        )

        self.conv1x1_value = nn.Conv2d(num_channels, value_head_channels, 1)
        self.conv1x1_policy = nn.Conv2d(num_channels, policy_head_channels, 1)
        
        if norm_type == 'BN':
            self.norm_value = nn.BatchNorm2d(value_head_channels)
            self.norm_policy = nn.BatchNorm2d(policy_head_channels)
        elif norm_type == 'LN':
            if downsample:
                self.norm_value = nn.LayerNorm([value_head_channels, math.ceil(observation_shape[-2] / 16), math.ceil(observation_shape[-1] / 16)])
                self.norm_policy = nn.LayerNorm([policy_head_channels, math.ceil(observation_shape[-2] / 16), math.ceil(observation_shape[-1] / 16)])
            else:
                self.norm_value = nn.LayerNorm([value_head_channels, observation_shape[-2], observation_shape[-1]])
                self.norm_policy = nn.LayerNorm([policy_head_channels, observation_shape[-2], observation_shape[-1]])
        
        self.flatten_output_size_for_value_head = flatten_output_size_for_value_head
        self.flatten_output_size_for_policy_head = flatten_output_size_for_policy_head
        self.activation = activation

        self.fc_value = MLP(
            in_channels=self.flatten_output_size_for_value_head,
            hidden_channels=fc_value_layers[0],
            out_channels=output_support_size,
            layer_num=len(fc_value_layers) + 1,
            activation=self.activation,
            norm_type=norm_type,
            output_activation=False,
            output_norm=False,
            # last_linear_layer_init_zero=True is beneficial for convergence speed.
            last_linear_layer_init_zero=last_linear_layer_init_zero
        )
        self.fc_policy = MLP(
            in_channels=self.flatten_output_size_for_policy_head,
            hidden_channels=fc_policy_layers[0],
            out_channels=action_space_size,
            layer_num=len(fc_policy_layers) + 1,
            activation=self.activation,
            norm_type=norm_type,
            output_activation=False,
            output_norm=False,
            # last_linear_layer_init_zero=True is beneficial for convergence speed.
            last_linear_layer_init_zero=last_linear_layer_init_zero
        )

    def forward(self, latent_state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Overview:
            Forward computation of the prediction network.
        Arguments:
            - latent_state (:obj:`torch.Tensor`): input tensor with shape (B, latent_state_dim).
        Returns:
            - policy (:obj:`torch.Tensor`): policy tensor with shape (B, action_space_size).
            - value (:obj:`torch.Tensor`): value tensor with shape (B, output_support_size).
        """
        for res_block in self.resblocks:
            latent_state = res_block(latent_state)

        value = self.conv1x1_value(latent_state)
        value = self.norm_value(value)
        value = self.activation(value)

        policy = self.conv1x1_policy(latent_state)
        policy = self.norm_policy(policy)
        policy = self.activation(policy)

        value = value.reshape(-1, self.flatten_output_size_for_value_head)
        policy = policy.reshape(-1, self.flatten_output_size_for_policy_head)

        value = self.fc_value(value)
        policy = self.fc_policy(policy)
        return policy, value


class PredictionNetworkMLP(nn.Module):

    def __init__(
            self,
            action_space_size,
            num_channels,
            common_layer_num: int = 2,
            fc_value_layers: SequenceType = [32],
            fc_policy_layers: SequenceType = [32],
            output_support_size: int = 601,
            last_linear_layer_init_zero: bool = True,
            activation: Optional[nn.Module] = nn.ReLU(inplace=True),
            norm_type: Optional[str] = 'BN',
    ):
        """
        Overview:
            The definition of policy and value prediction network with Multi-Layer Perceptron (MLP),
            which is used to predict value and policy by the given latent state.
        Arguments:
            - action_space_size: (:obj:`int`): Action space size, usually an integer number. For discrete action \
                space, it is the number of discrete actions.
            - num_channels (:obj:`int`): The channels of latent states.
            - fc_value_layers (:obj:`SequenceType`): The number of hidden layers used in value head (MLP head).
            - fc_policy_layers (:obj:`SequenceType`): The number of hidden layers used in policy head (MLP head).
            - output_support_size (:obj:`int`): The size of categorical value output.
            - last_linear_layer_init_zero (:obj:`bool`): Whether to use zero initializations for the last layer of \
                dynamics/prediction mlp, default sets it to True.
            - activation (:obj:`Optional[nn.Module]`): Activation function used in network, which often use in-place \
                operation to speedup, e.g. ReLU(inplace=True).
            - norm_type (:obj:`str`): The type of normalization in networks. defaults to 'BN'.
        """
        super().__init__()
        self.num_channels = num_channels

        # ******* common backbone ******
        self.fc_prediction_common = MLP(
            in_channels=self.num_channels,
            hidden_channels=self.num_channels,
            out_channels=self.num_channels,
            layer_num=common_layer_num,
            activation=activation,
            norm_type=norm_type,
            output_activation=True,
            output_norm=True,
            # last_linear_layer_init_zero=False is important for convergence
            last_linear_layer_init_zero=False,
        )

        # ******* value and policy head ******
        self.fc_value_head = MLP(
            in_channels=self.num_channels,
            hidden_channels=fc_value_layers[0],
            out_channels=output_support_size,
            layer_num=len(fc_value_layers) + 1,
            activation=activation,
            norm_type=norm_type,
            output_activation=False,
            output_norm=False,
            # last_linear_layer_init_zero=True is beneficial for convergence speed.
            last_linear_layer_init_zero=last_linear_layer_init_zero
        )
        self.fc_policy_head = MLP(
            in_channels=self.num_channels,
            hidden_channels=fc_policy_layers[0],
            out_channels=action_space_size,
            layer_num=len(fc_policy_layers) + 1,
            activation=activation,
            norm_type=norm_type,
            output_activation=False,
            output_norm=False,
            # last_linear_layer_init_zero=True is beneficial for convergence speed.
            last_linear_layer_init_zero=last_linear_layer_init_zero
        )

    def forward(self, latent_state: torch.Tensor):
        """
        Overview:
            Forward computation of the prediction network.
        Arguments:
            - latent_state (:obj:`torch.Tensor`): input tensor with shape (B, latent_state_dim).
        Returns:
            - policy (:obj:`torch.Tensor`): policy tensor with shape (B, action_space_size).
            - value (:obj:`torch.Tensor`): value tensor with shape (B, output_support_size).
        """
        x_prediction_common = self.fc_prediction_common(latent_state)

        value = self.fc_value_head(x_prediction_common)
        policy = self.fc_policy_head(x_prediction_common)
        return policy, value

"""
Source inspiration to https://github.com/CompVis/taming-transformers
"""

class SimpleDecoder(nn.Module):
    def __init__(self, in_channels=4, out_channels=12):
        super().__init__()
        self.up1 = nn.ConvTranspose2d(in_channels, 128, kernel_size=3, stride=2, padding=1, output_padding=1)
        self.block1 = ImportedResnetBlock(in_channels=128, out_channels=128, temb_channels=0, dropout=0.0)
        self.up2 = nn.ConvTranspose2d(128, 64, kernel_size=3, stride=2, padding=1, output_padding=1)
        self.block2 = ImportedResnetBlock(in_channels=64, out_channels=64, temb_channels=0, dropout=0.0)
        self.up3 = nn.ConvTranspose2d(64, 32, kernel_size=3, stride=2, padding=1, output_padding=1)
        self.block3 = ImportedResnetBlock(in_channels=32, out_channels=32, temb_channels=0, dropout=0.0)
        self.up4 = nn.ConvTranspose2d(32, 32, kernel_size=3, stride=2, padding=1, output_padding=1)
        self.norm_out = ImportedNormalize(32)
        self.conv_out = nn.Conv2d(32, out_channels, kernel_size=3, stride=1, padding=1)
        
        for params in self.parameters():
            params.requires_grad_(True)

    def forward(self, x):
        x = self.up1(x)
        x = self.block1(x, None)
        x = self.up2(x)
        x = self.block2(x, None)
        x = self.up3(x)
        x = self.block3(x, None)
        x = self.up4(x)
        x = self.norm_out(x)
        x = Importednonlinearity(x)
        x = self.conv_out(x)
        return x

def Importednonlinearity(x: torch.Tensor) -> torch.Tensor:
    # swish
    return x * torch.sigmoid(x)


def ImportedNormalize(in_channels: int) -> nn.Module:
    return torch.nn.GroupNorm(num_groups=int(in_channels/2), num_channels=in_channels, eps=1e-6, affine=True)


class ImportedUpsample(nn.Module):
    def __init__(self, in_channels: int, with_conv: bool) -> None:
        super().__init__()
        self.with_conv = with_conv
        if self.with_conv:
            self.conv = torch.nn.Conv2d(in_channels,
                                        in_channels,
                                        kernel_size=3,
                                        stride=1,
                                        padding=3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.nn.functional.interpolate(x, scale_factor=2.0, mode="nearest")
        if self.with_conv:
            x = self.conv(x)
        return x


class ImportedDownsample(nn.Module):
    def __init__(self, in_channels: int, with_conv: bool) -> None:
        super().__init__()
        self.with_conv = with_conv
        if self.with_conv:
            # no asymmetric padding in torch conv, must do it ourselves
            self.conv = torch.nn.Conv2d(in_channels,
                                        in_channels,
                                        kernel_size=3,
                                        stride=2,
                                        padding=0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.with_conv:
            pad = (0, 1, 0, 1)
            x = torch.nn.functional.pad(x, pad, mode="constant", value=0)
            x = self.conv(x)
        else:
            x = torch.nn.functional.avg_pool2d(x, kernel_size=2, stride=2)
        return x


class ImportedResnetBlock(nn.Module):
    def __init__(self, *, in_channels: int, out_channels: int = None, conv_shortcut: bool = False,
                 dropout: float, temb_channels: int = 512) -> None:
        super().__init__()
        self.in_channels = in_channels
        out_channels = in_channels if out_channels is None else out_channels
        self.out_channels = out_channels
        self.use_conv_shortcut = conv_shortcut

        self.norm1 = ImportedNormalize(in_channels)
        self.conv1 = torch.nn.Conv2d(in_channels,
                                     out_channels,
                                     kernel_size=3,
                                     stride=1,
                                     padding=1)
        if temb_channels > 0:
            self.temb_proj = torch.nn.Linear(temb_channels,
                                             out_channels)
        self.norm2 = ImportedNormalize(out_channels)
        self.dropout = torch.nn.Dropout(dropout)
        self.conv2 = torch.nn.Conv2d(out_channels,
                                     out_channels,
                                     kernel_size=3,
                                     stride=1,
                                     padding=1)
        if self.in_channels != self.out_channels:
            if self.use_conv_shortcut:
                self.conv_shortcut = torch.nn.Conv2d(in_channels,
                                                     out_channels,
                                                     kernel_size=3,
                                                     stride=1,
                                                     padding=2)
            else:
                self.nin_shortcut = torch.nn.Conv2d(in_channels,
                                                    out_channels,
                                                    kernel_size=1,
                                                    stride=1,
                                                    padding=0)

    def forward(self, x: torch.Tensor, temb: torch.Tensor) -> torch.Tensor:
        h = x
        h = self.norm1(h)
        h = Importednonlinearity(h)
        h = self.conv1(h)

        if temb is not None:
            h = h + self.temb_proj(Importednonlinearity(temb))[:, :, None, None]

        h = self.norm2(h)
        h = Importednonlinearity(h)
        h = self.dropout(h)
        h = self.conv2(h)

        if self.in_channels != self.out_channels:
            if self.use_conv_shortcut:
                x = self.conv_shortcut(x)
            else:
                x = self.nin_shortcut(x)
        new = x + h
        return x + h


class ImportAttnBlock(nn.Module):
    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.in_channels = in_channels

        self.norm = ImportedNormalize(in_channels)
        self.q = torch.nn.Conv2d(in_channels,
                                 in_channels,
                                 kernel_size=1,
                                 stride=1,
                                 padding=0)
        self.k = torch.nn.Conv2d(in_channels,
                                 in_channels,
                                 kernel_size=1,
                                 stride=1,
                                 padding=0)
        self.v = torch.nn.Conv2d(in_channels,
                                 in_channels,
                                 kernel_size=1,
                                 stride=1,
                                 padding=0)
        self.proj_out = torch.nn.Conv2d(in_channels,
                                        in_channels,
                                        kernel_size=1,
                                        stride=1,
                                        padding=0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h_ = x
        h_ = self.norm(h_)
        q = self.q(h_)
        k = self.k(h_)
        v = self.v(h_)

        # compute attention
        b, c, h, w = q.shape
        q = q.reshape(b, c, h * w)
        q = q.permute(0, 2, 1)      # b,hw,c
        k = k.reshape(b, c, h * w)  # b,c,hw
        w_ = torch.bmm(q, k)        # b,hw,hw    w[b,i,j]=sum_c q[b,i,c]k[b,c,j]
        w_ = w_ * (int(c) ** (-0.5))
        w_ = torch.nn.functional.softmax(w_, dim=2)

        # attend to values
        v = v.reshape(b, c, h * w)
        w_ = w_.permute(0, 2, 1)   # b,hw,hw (first hw of k, second of q)
        h_ = torch.bmm(v, w_)     # b, c,hw (hw of q) h_[b,c,j] = sum_i v[b,c,i] w_[b,i,j]
        h_ = h_.reshape(b, c, h, w)

        h_ = self.proj_out(h_)

        return x + h_
