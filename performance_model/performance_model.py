import gc

import numpy as np
import torch
from thop import profile


class PerformanceModel:
    def __init__(self, model, train_loader, config, overhead_gd_top_k=False,
                 overhead_gd_top_k_mc=False, overhead_re_pruning=False, overhead_admm=True, logger=None):

        self.config = config
        self.logger = logger
        self.est_oh_gd_top_k = overhead_gd_top_k
        self.est_oh_gd_top_k_mc = overhead_gd_top_k_mc
        self.est_oh_re_pruning = overhead_re_pruning
        self.est_oh_admm = overhead_admm

        in_shape = next(enumerate(train_loader))[1][0].shape
        self.macs = profile(model,
                            inputs=(torch.rand(in_shape[0],
                                               in_shape[1],
                                               in_shape[2],
                                               in_shape[3]),),
                            ret_layer_info=True)[2]

        self.macs = profile(model,
                            inputs=(torch.rand(in_shape[0],
                                               in_shape[1],
                                               in_shape[2],
                                               in_shape[3]),),
                            ret_layer_info=True)[2]
        self.flops_accumulated = 1e-38  # 0.0
        self.flops_accumulated_base = 1e-38  # 0.0
        self.flops_current = 1e-38  # 0.0
        self.flops_current_base = 1e-38  # 0.0

        self.flops_accumulated_fwd = 1e-38  # 0.0
        self.flops_accumulated_base_fwd = 1e-38  # 0.0
        self.flops_current_fwd = 1e-38  # 0.0
        self.flops_current_base_fwd = 1e-38  # 0.0

        self.flops_accumulated_bwd = 1e-38  # 0.0
        self.flops_accumulated_base_bwd = 1e-38  # 0.0
        self.flops_current_bwd = 1e-38  # 0.0
        self.flops_current_base_bwd = 1e-38  # 0.0

        self.sparsity_current = 0.0
        self.c_sparsity_current = 0.0
        self.l_sparsity_current = 0.0

    def __estimate_overhead_re_pruning_search(self, model):
        # https://coek.info/pdf-algorithms-54ed9513cfa623e30da35434ea7edcc833265.html
        # https://mast.queensu.ca/~andrew/notes/pdf/2010a.pdf
        oh_search_space_iteration = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                density = (torch.count_nonzero(param) / torch.numel(param)).numpy()
                # RE Pruning
                if 'conv' in name or 'features' in name:
                    oh_w0 = 2 * torch.count_nonzero(param) / self.config.get('SPECIFICATION', 'lb',
                                                                             int)  # Obtaining W0 from accumulated grads very lb batches
                    oh_metric = 2 * (density * (np.prod(list(param.shape)))) / self.config.get('SPECIFICATION', 'lb',
                                                                                               int)  # 2 times Frobenius Norm every lb batches
                    oh_search_space_iteration += oh_w0 + oh_metric * self.config.get('SPECIFICATION', 'sample_c',
                                                                                     int) * self.config.get(
                        'SPECIFICATION', 'scale_c', float)  # metric times attempts times scale
                if 'fc' in name or 'classifier' in name:
                    oh_w0 = 2 * torch.count_nonzero(param) / self.config.get('SPECIFICATION', 'lb', int)
                    oh_metric = 2 * (density * (np.prod(list(param.shape)))) / self.config.get('SPECIFICATION', 'lb',
                                                                                               int)
                    oh_search_space_iteration += oh_w0 + oh_metric * self.config.get('SPECIFICATION', 'sample_l',
                                                                                     int) * self.config.get(
                        'SPECIFICATION', 'scale_l', float)
        return oh_search_space_iteration

    def __estimate_overhead_mask_computation(self, model):
        oh_mask_computation = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                if 'conv' in name or 'features' in name:
                    oh_mask_computation += (
                                self.config.get('SPECIFICATION', 'metric_q_c', float) * self.config.get('SPECIFICATION',
                                                                                                        'sample_c', int)
                                * torch.numel(param)
                                / self.config.get('SPECIFICATION', 'lb', int))
                if 'fc' in name or 'classifier' in name:
                    oh_mask_computation += (
                                self.config.get('SPECIFICATION', 'metric_q_l', float) * self.config.get('SPECIFICATION',
                                                                                                        'sample_l', int)
                                * torch.numel(param)
                                / self.config.get('SPECIFICATION', 'lb', int))
        return oh_mask_computation

    def __estimate_overhead_mask_application(self, model):
        oh_mask_application = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                if 'conv' in name or 'features' in name or 'fc' in name or 'classifier' in name:
                    oh_mask_application += torch.numel(
                        param) * 2  # times two if grads masked
        return oh_mask_application

    def __estimate_overhead_gd_top_k(self, model):
        # https://coek.info/pdf-algorithms-54ed9513cfa623e30da35434ea7edcc833265.html
        # https://mast.queensu.ca/~andrew/notes/pdf/2010a.pdf
        oh_search_space_iteration = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                density = (torch.count_nonzero(param) / torch.numel(param)).numpy()
                if 'conv' in name or 'features' in name or 'fc' in name or 'classifier' in name:
                    oh_metric = (density * (np.prod(list(param.shape)))) / self.config.get('SPECIFICATION', 'lb',
                                                                                           int)  # 1 times Frobenius Norm every lb batches
                    oh_search_space_iteration += oh_metric
        return oh_search_space_iteration

    def __estimate_overhead_grad_accumulation(self, model):
        oh_grad_accumulation = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                if 'conv' in name or 'features' in name or 'fc' in name or 'classifier' in name:
                    oh_grad_accumulation += torch.count_nonzero(param)  # accumulation of gradients every batch
        return oh_grad_accumulation

    def __estimate_overhead_admm(self, model):
        oh_admm = 0
        for name, param in model.named_parameters():
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                if 'conv' in name or 'features' in name or 'fc' in name or 'classifier' in name:
                    oh_admm += torch.numel(param) * 3 + 2 * (np.prod(list(param.shape)))  # u, z + norm
        return oh_admm

    def __estimate_overhead(self, model, epoch=None):
        # Assumptions: regularized baseline with gradient normalzation
        oh_grad_accumulation, oh_re_pruning, oh_gd_top_k, oh_gd_top_k_mc, oh_admm = 0, 0, 0, 0, 0
        if self.est_oh_re_pruning or self.est_oh_gd_top_k or self.est_oh_gd_top_k_mc:
            oh_grad_accumulation += self.__estimate_overhead_grad_accumulation(model).item()
        if self.est_oh_gd_top_k:
            oh_gd_top_k += self.__estimate_overhead_gd_top_k(model).item()
        if self.est_oh_re_pruning:
            if epoch is None or epoch < self.config.get('SPECIFICATION', 'prune_epochs', int):
                oh_re_pruning += self.__estimate_overhead_re_pruning_search(model).item()
                oh_re_pruning += self.__estimate_overhead_mask_computation(model)
                oh_re_pruning += self.__estimate_overhead_mask_application(model)
            else:
                oh_re_pruning += self.__estimate_overhead_mask_application(
                    model)  # thresholding approx. as mask aplication
        if self.est_oh_gd_top_k_mc:
            if epoch is None or epoch % self.config.get('SPECIFICATION', 'se', int) == 0:
                oh_gd_top_k_mc = self.__estimate_overhead_gd_top_k(model).item()
        if self.est_oh_admm:
            oh_admm = self.__estimate_overhead_admm(model).item()
            oh_admm += self.__estimate_overhead_mask_application(model)

        return (oh_gd_top_k_mc + oh_gd_top_k + oh_re_pruning + oh_grad_accumulation + oh_admm) * 1e-9  # GFLOPs

    def eval(self, model, ac=1, epoch=None, admm_mask=None):
        stats_batch = self.__current_flops(model, ac, admm_mask)
        self.flops_current = stats_batch[0]
        self.flops_current_base = stats_batch[1]
        self.flops_accumulated += stats_batch[0]
        self.flops_accumulated_base += stats_batch[1]

        self.sparsity_current = stats_batch[2]

        self.flops_current_fwd = stats_batch[3]
        self.flops_current_base_fwd = stats_batch[4]
        self.flops_accumulated_fwd += stats_batch[3]
        self.flops_accumulated_base_fwd += stats_batch[4]

        self.flops_current_bwd = stats_batch[5]
        self.flops_current_base_bwd = stats_batch[6]
        self.flops_accumulated_bwd += stats_batch[5]
        self.flops_accumulated_base_bwd += stats_batch[6]

        self.c_sparsity_current = stats_batch[7]
        self.l_sparsity_current = stats_batch[8]
        self.g_sparsity_current = stats_batch[9]
        self.oh = self.__estimate_overhead(model, epoch)

    def __current_flops(self, model, ac, admm_mask):
        flops_i, flops_i_base, nonzero_i, c_nonzero_i, l_nonzero_i, g_nonzero_i = 0, 0, 0, 0, 0, 0
        flops_i_fwd, flops_i_base_fwd = 0, 0
        flops_i_bwd, flops_i_base_bwd = 0, 0
        total = 0
        total_c = 0
        total_l = 0
        total_g = 0
        for name, param in model.named_parameters():
            # https://openai.com/blog/ai-and-compute/
            prefix = name.split('.')[0]
            postfix = name.split('.')[1]
            if postfix != 'bias':
                nonzero = torch.count_nonzero(param).numpy()
                c_nonzero = 0.0
                l_nonzero = 0.0
                total += torch.numel(param)
                if 'conv' in name or 'features' in name:
                    # print(name, density)
                    c_nonzero = nonzero
                    total_c += torch.numel(param)
                if 'fc' in name or 'classifier' in name:
                    l_nonzero = nonzero
                    total_l += torch.numel(param)

                if param.grad is not None:
                    total_g += torch.numel(param.grad)
                    g_nonzero = None
                    if admm_mask is not None and name in admm_mask:
                        g_nonzero = torch.count_nonzero(param.grad * admm_mask[name])
                    else:
                        g_nonzero = torch.count_nonzero(param.grad)
                    g_nonzero_i += g_nonzero
                    flops_i_n_fwd = self.macs[prefix][0] * 2 * (nonzero / torch.numel(param))  # fwd
                    flops_i_n_bwd = 2 * flops_i_n_fwd * (
                                g_nonzero / torch.numel(param.grad)).numpy() / ac  # bwd = 2*fwd*g_sparsity/ac
                    flops_i_fwd += flops_i_n_fwd
                    flops_i_bwd += flops_i_n_bwd
                    flops_i += flops_i_n_fwd + flops_i_n_bwd
                else:
                    flops_i_fwd += self.macs[prefix][0] * 2 * (nonzero / torch.numel(param)).numpy()
                    flops_i += self.macs[prefix][0] * 2 * (nonzero / torch.numel(param)).numpy()

                nonzero_i += nonzero
                c_nonzero_i += c_nonzero
                l_nonzero_i += l_nonzero

                if param.grad is not None:
                    flops_i_n_fwd = self.macs[prefix][0] * 2  # fwd,bwd updaten
                    flops_i_n_bwd = 2 * flops_i_n_fwd
                    flops_i_base_fwd += flops_i_n_fwd
                    flops_i_base_bwd += flops_i_n_bwd
                    flops_i_base += flops_i_n_fwd + flops_i_n_bwd
                else:
                    flops_i_n_fwd = self.macs[prefix][0] * 2
                    flops_i_base += flops_i_n_fwd

        sp_t = 1 - nonzero_i / total if total > 0 else 0
        sp_c = 1 - c_nonzero_i / total_c if total_c > 0 else 0
        sp_l = 1 - l_nonzero_i / total_l if total_l > 0 else 0
        sp_g = (1 - g_nonzero_i / total_g).numpy() if total_g > 0 else 0

        return flops_i * 1e-9, flops_i_base * 1e-9, sp_t, flops_i_fwd, \
               flops_i_base_fwd, flops_i_bwd, flops_i_base_bwd, sp_c, sp_l, sp_g

    def print_cuda_status(self):
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            print('CUDA available, device:', torch.cuda.current_device(),
                  torch.cuda.get_device_name(torch.cuda.current_device()))
        else:
            print('CUDA not available or nor devices found')

    def print_memstats(self, batch_idx, interval):
        if batch_idx % interval == 0:
            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            print('Using device:', device)
            print('Batch index:', batch_idx)

            # torch.cuda.empty_cache()
            if device.type == 'cuda':
                print(torch.cuda.get_device_name(0))
                print('Memory Usage:')
                print('Allocated:', round(torch.cuda.memory_allocated(0) / 1024 ** 3, 1), 'GB')
                print('Cached:   ', round(torch.cuda.memory_cached(0) / 1024 ** 3, 1), 'GB')
                # print(torch.cuda.memory_stats().keys())
                print('Inactive:  ',
                      round(torch.cuda.memory_stats()['inactive_split_bytes.all.current'] / 1024 ** 3, 1),
                      'GB')
                # print(torch.cuda.memory_snapshot())

                ctr = 0
                ctr_mem = 0
                for obj in gc.get_objects():
                    try:
                        if torch.is_tensor(obj) or (hasattr(obj, 'data') and torch.is_tensor(obj.data)):
                            ctr += 1
                            ctr_mem += obj.size()
                            # print(type(obj), obj.size())
                    except:
                        pass
                print('Referenced objects:', ctr)
                print('Referenced objects size:', ctr_mem)

    def print_perf_stats(self):
        print('Total SU', self.flops_accumulated_base / self.flops_accumulated,
              '\nCurrent SU', self.flops_current_base / self.flops_current,
              '\nTotal SU FWD',
              self.flops_accumulated_base_fwd / self.flops_accumulated_fwd,
              '\nCurrent SU FWD',
              self.flops_current_base_fwd / self.flops_current_fwd,
              '\nTotal SU BWD',
              self.flops_accumulated_base_bwd / self.flops_accumulated_bwd,
              '\nCurrent SU BWD',
              self.flops_current_base_bwd / self.flops_current_bwd,
              '\nCurrent Sparsity', self.sparsity_current,
              '\nCurrent Channel Sparsity', self.c_sparsity_current,
              '\nCurrent Linear Sparsity', self.l_sparsity_current,
              '\nCurrent Gradient Sparsity', self.g_sparsity_current,
              '\nCurrent Relative Overhead', self.oh / self.flops_current,
              flush=True)

    def log_perf_stats(self):
        if self.logger is not None:
            self.logger.log('total_su', float(self.flops_accumulated_base / self.flops_accumulated))
            self.logger.log('current_su', float(self.flops_current_base / self.flops_current))
            self.logger.log('total_su_fwd', float(self.flops_accumulated_base_fwd / self.flops_accumulated_fwd))
            self.logger.log('current_su_fwd', float(self.flops_current_base_fwd / self.flops_current_fwd))
            self.logger.log('total_su_bwd', float(self.flops_accumulated_base_bwd / self.flops_accumulated_bwd))
            self.logger.log('current_su_bwd', float(self.flops_current_base_bwd / self.flops_current_bwd))
            self.logger.log('current_sparsity', float(self.sparsity_current))
            self.logger.log('current_channel_sparsity', float(self.c_sparsity_current))
            self.logger.log('current_linear_sparsity', float(self.l_sparsity_current))
            self.logger.log('current_gradient_sparsity', float(self.g_sparsity_current))
            self.logger.log('current_relative_overhead', float(self.oh / self.flops_current))

    def log_layer_sparsity(self, model):
        if self.logger is not None:
            for name, param in model.named_parameters():
                prefix = name.split('.')[0]
                postfix = name.split('.')[1]
                if not 'bias' in name:
                    if 'conv' in name or 'features' in name or 'fc' in name or 'classifier' in name:
                        key = 'sparsity_{}'.format(name)
                        sparsity = (1 - torch.count_nonzero(param) / torch.numel(param)).item()
                        self.logger.log(key, sparsity)
                        if param.grad is not None:
                            key = 'sparsity_grad_{}'.format(name)
                            sparsity = (1 - torch.count_nonzero(param.grad) / torch.numel(param)).item()
                            self.logger.log(key, sparsity)
