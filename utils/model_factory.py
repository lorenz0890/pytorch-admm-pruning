import math

import torchvision.models
from torch import nn
from torchvision import datasets, transforms
import torch

from model import LeNet, AlexNet, VGG16, ResNet18
from .custom_init import truncated_normal_variance_scaling

class ModelFactory:
    def __init__(self):
        pass

    def get_model(self, config):
        use_cuda = not config.get('OTHER', 'no_cuda', bool) and torch.cuda.is_available()
        device = torch.device("cuda" if use_cuda else "cpu")
        model = None
        if config.get('EXPERIMENT', 'model', str) == 'lenet':
            model = LeNet().to(device)
        elif config.get('EXPERIMENT', 'model', str) == 'alexnet':
            model = AlexNet().to(device)
        elif config.get('EXPERIMENT', 'model', str) == 'vgg16':
            model = VGG16().to(device) #torchvision.models.vgg16().to(device) #TODO add bn VGG
        elif config.get('EXPERIMENT', 'model', str) == 'vgg16b':
            model = VGG16().to(device)#torchvision.models.vgg16_bn().to(device)
        elif config.get('EXPERIMENT', 'model', str) == 'resnet18':
            model = ResNet18().to(device)#torchvision.models.resnet18().to(device)

        def init_weights(m):
            if hasattr(m, 'weight') and len(m.weight.shape) > 1:
                truncated_normal_variance_scaling(m.weight, 0.5)
            if hasattr(m, 'bias') and hasattr(m.bias, 'data'):
                stdv = 1. / math.sqrt(m.weight.size(1))
                m.bias.data.uniform_(-stdv, stdv)

        model.apply(init_weights)
        return model