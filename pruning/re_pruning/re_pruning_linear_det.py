import numpy as np
import torch

from pruning import RePruning


class RePruningLinearDet(RePruning):
    def __init__(self, softness, magnitude_threshold, metric_quantile, lr, sample, lb, scale):
        super().__init__()
        self.masks = {}
        self.strength = softness
        self.magnitude_threshold = magnitude_threshold
        self.metric_quantile = metric_quantile
        self.sample = sample
        self.lr = lr
        self.lb = lb
        self.scale = scale
        self.metrics = {}

    def compute_mask(self, model, acm_g, batch_idx):
        with torch.no_grad():
            if (batch_idx + 1) % self.lb == 0:
                self.metrics = {}
                for sample in range(self.sample):
                    for i, (n, p) in enumerate(model.named_parameters()):
                        if p.grad is not None and not 'bias' in n and ('fc' in n or 'classifier' in n):
                            if len(p.shape) == 2:
                                W = p
                                G = acm_g[n]
                                W0 = W - self.lr * G
                                W = W / torch.norm(W)
                                W0 = W0 / torch.norm(W0)
                                sz_k = np.random.randint(int(p.shape[0] * self.scale) + 1, p.shape[0] + 1)
                                sz_j = np.random.randint(int(p.shape[1] * self.scale) + 1, p.shape[1] + 1)
                                for k in range(0, p.shape[0] - sz_k, sz_k):
                                    for j in range(0, p.shape[1] - sz_j, sz_j):
                                        nz_w = W[k:k + sz_k, j + sz_j].count_nonzero()  # cheap in sparse tensor format
                                        nz_w0 = W0[k:k + sz_k, j + sz_j].count_nonzero()
                                        if not "{}:{}:{}:{}:{}".format(n, k, j, sz_k, sz_j) in self.metrics and (
                                                nz_w + nz_w0) >= 1:
                                            norm_w = torch.norm(W[k:k + sz_k, j + sz_j]) if nz_w >= 1 else 0
                                            if norm_w != 0:
                                                norm_w0 = torch.norm(W0[k:k + sz_k, j:j + sz_j]) if nz_w0 >= 1 else 0
                                                metric = (norm_w / norm_w0).item() if norm_w0 > 0 else float('inf')
                                                self.metrics["{}:{}:{}:{}:{}".format(n, k, j, sz_k, sz_j)] = metric
                                            else:
                                                self.metrics["{}:{}:{}:{}:{}".format(n, k, j, sz_k, sz_j)] = float(
                                                    'inf')

                metric_vals = list(self.metrics.values())
                if len(metric_vals) > 0:
                    metric_threshold = np.quantile(metric_vals, self.metric_quantile)
                    candidates = {}
                    for key in self.metrics:
                        if self.metrics[key] <= metric_threshold and not np.isnan(self.metrics[key]) and not \
                        self.metrics[key] == float('inf'):
                            idx = key.split(':')
                            if idx[0] not in candidates:
                                candidates[idx[0]] = []
                            candidates[idx[0]].append(key)
                    # print(metric_threshold, flush=True)
                    for n in candidates:
                        # print(n, model.state_dict()[n].data.shape, len(candidates[n]), flush=True)
                        mask = torch.ones_like(model.state_dict()[n].data)
                        for key in candidates[n]:
                            # print(key, flush=True)
                            idx = key.split(':')
                            mask[int(idx[1]):int(idx[1]) + int(idx[3])][int(idx[2]):int(idx[2]) + int(idx[4])] = mask[
                                                                                                                 int(
                                                                                                                     idx[
                                                                                                                         1]):int(
                                                                                                                     idx[
                                                                                                                         1]) + int(
                                                                                                                     idx[
                                                                                                                         3])][
                                                                                                                 int(
                                                                                                                     idx[
                                                                                                                         2]):int(
                                                                                                                     idx[
                                                                                                                         2]) + int(
                                                                                                                     idx[
                                                                                                                         4])] * 0.0
                        '''
                        mask = mask * torch.where(
                            torch.abs(model.state_dict()[n].data) > self.magnitude_threshold,
                            torch.ones_like(model.state_dict()[n].data),
                            torch.zeros_like(model.state_dict()[n].data))
                        '''
                        if n in self.masks:
                            self.masks[n] = self.masks[n] * mask
                        else:
                            self.masks[n] = mask

    def apply_mask(self, model):
        with torch.no_grad():
            for i, (n, p) in enumerate(model.named_parameters()):
                if p.grad is not None and not 'bias' in n and ('fc' in n or 'classifier' in n):
                    if n in self.masks:
                        p.data = p.data * (self.masks[n] + (torch.ones_like(p.data) - self.masks[n]) * self.strength)
                        if p.grad.data is not None:
                            p.grad.data = p.grad.data * self.masks[
                                n]  # (self.masks[n] + (torch.ones_like(p.data) - self.masks[n]) * self.strength)

    def apply_threshold(self, model):
        with torch.no_grad():
            for i, (n, p) in enumerate(model.named_parameters()):
                if p.grad is not None and not 'bias' in n and ('fc' in n or 'classifier' in n):
                    p.data = torch.where(torch.abs(p.data) > self.magnitude_threshold, p.data, torch.zeros_like(p.data))
                    if p.grad.data is not None:
                        p.grad.data = torch.where(torch.abs(p.grad.data) > self.magnitude_threshold, p.grad.data,
                                                  torch.zeros_like(p.grad.data))
