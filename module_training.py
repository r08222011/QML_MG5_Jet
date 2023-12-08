import time
import torch
from sklearn import metrics

# pytorch_lightning
import lightning as L
import lightning.pytorch as pl

class TorchDataset(torch.utils.data.Dataset):
    def __init__(self, x, y):
        self.x = x
        self.y = y
    def __len__(self):
        return len(self.y)
    def __getitem__(self, idx):
        return self.x[idx], self.y[idx]

# Binary classification of graph data
class BinaryLitModel(L.LightningModule):
    def __init__(self, model, lr, optimizer=None, loss_func=None, graph=False):
        super().__init__()
        # self.save_hyperparameters(ignore=['model'])
        self.model     = model
        self.graph     = graph # whether the data input is a graph (using torch_geometric)
        self.optimizer = torch.optim.Adam(self.parameters(), lr=lr) if optimizer is None else optimizer
        self.loss_func = torch.nn.BCEWithLogitsLoss() if loss_func is None else loss_func

    def forward(self, data, mode):
        # predict y
        if self.graph == True:
            x, edge_index, batch = data.x, data.edge_index, data.batch
            x = self.model(x, edge_index, batch)
            y_true = data.y
        else:
            x, y_true = data
            x = self.model(x)
        x = x.squeeze(dim=-1)

        # calculate loss and accuracy
        y_pred = x > 0
        loss   = self.loss_func(x, y_true.float())
        acc    = (y_pred == y_true).float().mean()

        # calculate auc
        y_true  = y_true.detach().to("cpu")
        y_score = torch.sigmoid(x).detach().to("cpu") # because we use BCEWithLogitsLoss
        if mode == "train":
            self.y_train_true_buffer  = torch.cat((self.y_train_true_buffer, y_true))
            self.y_train_score_buffer = torch.cat((self.y_train_score_buffer, y_score))
        elif mode == "valid":
            self.y_valid_true_buffer  = torch.cat((self.y_valid_true_buffer, y_true))
            self.y_valid_score_buffer = torch.cat((self.y_valid_score_buffer, y_score))
        elif mode == "test":
            self.y_test_true_buffer  = torch.cat((self.y_test_true_buffer, y_true))
            self.y_test_score_buffer = torch.cat((self.y_test_score_buffer, y_score))
        return loss, acc

    def configure_optimizers(self):
        return self.optimizer

    def on_train_epoch_start(self):
        self.start_time     = time.time()
        self.y_train_true_buffer  = torch.tensor([])
        self.y_train_score_buffer = torch.tensor([])

    def on_train_epoch_end(self):
        self.end_time = time.time()
        delta_time    = self.end_time - self.start_time
        roc_auc       = metrics.roc_auc_score(self.y_train_true_buffer, self.y_train_score_buffer)
        self.log("epoch_time", delta_time, on_step=False, on_epoch=True)
        self.log("train_roc_auc", roc_auc, on_step=False, on_epoch=True)
        del self.y_train_true_buffer
        del self.y_train_score_buffer

    def training_step(self, data, batch_idx):
        batch_size = len(data.x) if self.graph is True else len(data[0])
        loss, acc = self.forward(data, mode="train")
        self.log("train_loss", loss, on_step=True, on_epoch=True, batch_size=batch_size)
        self.log("train_acc", acc, on_step=True, on_epoch=True, batch_size=batch_size)
        return loss
    
    def on_validation_epoch_start(self):
        self.y_valid_true_buffer  = torch.tensor([])
        self.y_valid_score_buffer = torch.tensor([])

    def on_validation_epoch_end(self):
        roc_auc = metrics.roc_auc_score(self.y_valid_true_buffer, self.y_valid_score_buffer)
        self.log("val_roc_auc", roc_auc, on_step=False, on_epoch=True)
        del self.y_valid_true_buffer
        del self.y_valid_score_buffer

    def validation_step(self, data, batch_idx):
        batch_size = len(data.x) if self.graph is True else len(data[0])
        _, acc = self.forward(data, mode="valid")
        self.log("valid_acc", acc, on_step=True, on_epoch=True, batch_size=batch_size)

    def on_test_epoch_start(self):
        self.y_test_true_buffer  = torch.tensor([])
        self.y_test_score_buffer = torch.tensor([])

    def on_test_epoch_end(self):
        roc_auc = metrics.roc_auc_score(self.y_test_true_buffer, self.y_test_score_buffer)
        self.log("test_roc_auc", roc_auc, on_step=False, on_epoch=True)
        del self.y_test_true_buffer
        del self.y_test_score_buffer

    def test_step(self, data, batch_idx):
        batch_size = len(data.x) if self.graph is True else len(data[0])
        _, acc = self.forward(data, mode="test")
        self.log("test_acc", acc, on_step=True, on_epoch=True, batch_size=batch_size)

# wandb functions
def wandb_monitor(model, logger_config, *args):
    import wandb
    from lightning.pytorch.loggers import WandbLogger
    wandb.login()
    wandb_logger = WandbLogger(**logger_config)
    wandb_config = {}
    wandb_config.update(logger_config)
    for config in args:
        wandb_config.update(config)
    wandb_logger.experiment.config.update(wandb_config, allow_val_change=True)
    wandb_logger.watch(model, log="all")
    return wandb_logger

def wandb_finish():
    import wandb
    wandb.finish()