from __future__ import print_function
from utils import Parser
from utils import ExperimentFactory
from os import listdir
from os.path import isfile, join


from tqdm import tqdm
from functools import partialmethod
import sys, os

def blockPrint():
    # https://stackoverflow.com/questions/8391411/how-to-block-calls-to-print
    # https://stackoverflow.com/questions/37091673/silence-tqdms-output-while-running-tests-or-running-the-code-via-cron
    sys.stdout = open(os.devnull, 'w')
    tqdm.__init__ = partialmethod(tqdm.__init__, disable=True)

def enablePrint():
    # https://stackoverflow.com/questions/8391411/how-to-block-calls-to-print
    # https://stackoverflow.com/questions/37091673/silence-tqdms-output-while-running-tests-or-running-the-code-via-cron
    sys.stdout = sys.__stdout__
    tqdm.__init__ = partialmethod(tqdm.__init__, disable=False)

def main():
    config = Parser()
    experiment_factory = ExperimentFactory()

    #config.load('configs/admm_retrain/lenet_mnist.ini')
    #config.load('configs/admm_retrain/x_alexnet_cifar10.ini')
    #config.load('configs/admm_retrain/vgg16_cifar10_2.ini')

    #config.load('configs/admm_intra/lenet_mnist.ini')
    #config.load('configs/admm_intra/x_alexnet_cifar10.ini')

    #config.load('configs/gd_top_k/lenet_mnist.ini')
    #config.load('configs/gd_top_k/x_alexnet_cifar10.ini')
    #config.load('configs/gd_top_k/vgg16_cifar10_2.ini')

    #config.load('configs/gd_top_k_mc/lenet_mnist.ini')

    #config.load('configs/gd_top_k_mc_ac/lenet_mnist.ini')

    #config.load('configs/gd_top_k_mc_ac_dk/lenet_mnist.ini')
    #config.load('configs/gd_top_k_mc_ac_dk/x_alexnet_cifar10.ini')
    '''
    #config.load('configs/re_pruning/lenet_mnist.ini')
    config.load('configs/re_pruning/alexnet_cifar10.ini')
    #config.load('configs/re_pruning/mobilenet_v3_s_cifar10.ini')
    #config.load('configs/re_pruning/vgg11_cifar10.ini')
    #config.load('configs/re_pruning/vgg16_cifar10_2.ini')
    #config.load('configs/re_pruning/resnet18_cifar10.ini')


    experiment = experiment_factory.get_experiment(config)
    experiment.dispatch()

    '''
    #Batch mode
    path = 'configs/baseline/'
    fnames = [f for f in listdir(path) if isfile(join(path, f))]
    for fname in fnames:
        try:
            enablePrint()
            print(fname, flush=True)
            blockPrint()
            config.load(path+fname)
            experiment = experiment_factory.get_experiment(config)
            experiment.dispatch()
        except Exception as e:
            enablePrint()
            print(e, flush=True)
            blockPrint()

if __name__ == "__main__":
    main()