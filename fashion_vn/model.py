"""CNN+GAP image embedding and bag-of-words text embedding as in Han et al."""
import torch
from torch import nn
from torch.nn import functional as F
from torchvision import models, transforms
from PIL import ImageOps

class Letterbox:
    def __init__(self, size):
        self.size = size

    def __call__(self, im):
        return ImageOps.pad(ImageOps.exif_transpose(im).convert('RGB'),
                            (self.size, self.size), color=(255, 255, 255))

def image_transform(backbone):
    return transforms.Compose([Letterbox(299 if backbone == 'inception_v3' else 224),
                               transforms.ToTensor(),
                               transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

class Backbone(nn.Module):
    def __init__(self, name, pretrained=True):
        super().__init__()
        self.name = name
        if name == 'resnet18':
            m = models.resnet18(weights=models.ResNet18_Weights.DEFAULT if pretrained else None)
            self.features = nn.Sequential(*list(m.children())[:-2])
            self.channels, self.grid = 512, 7
        elif name == 'inception_v3':
            m = models.inception_v3(weights=models.Inception_V3_Weights.DEFAULT if pretrained else None,
                                    transform_input=False, init_weights=False)
            self.features = nn.Sequential(
                m.Conv2d_1a_3x3, m.Conv2d_2a_3x3, m.Conv2d_2b_3x3,
                nn.MaxPool2d(3, stride=2), m.Conv2d_3b_1x1, m.Conv2d_4a_3x3,
                nn.MaxPool2d(3, stride=2), m.Mixed_5b, m.Mixed_5c, m.Mixed_5d,
                m.Mixed_6a, m.Mixed_6b, m.Mixed_6c, m.Mixed_6d, m.Mixed_6e,
                m.Mixed_7a, m.Mixed_7b, m.Mixed_7c)
            self.channels, self.grid = 2048, 8
        else:
            raise ValueError(name)

    def forward(self, images):
        if self.name == 'inception_v3':
            # Reproduce torchvision Inception's pretrained _transform_input,
            # which the manual feature forward would otherwise bypass.
            mean = images.new_tensor([.485, .456, .406])[None, :, None, None]
            std = images.new_tensor([.229, .224, .225])[None, :, None, None]
            images = images * (std / .5) + (mean - .5) / .5
        return self.features(images)

class JointEmbedding(nn.Module):
    def __init__(self, channels, vocab_size, dim=512):
        super().__init__()
        self.image_projection = nn.Linear(channels, dim, bias=False)
        self.word_embedding = nn.Embedding(vocab_size, dim)
        nn.init.normal_(self.word_embedding.weight, std=.02)

    def image(self, pooled):
        return F.normalize(self.image_projection(pooled), dim=-1)

    def text(self, bow):
        return F.normalize(bow @ self.word_embedding.weight / bow.sum(1, keepdim=True).clamp_min(1), dim=-1)

def ranking_loss(x, v, groups, bow, margin=.2):
    """Bidirectional hinge loss; duplicate groups/identical descriptions aren't negatives."""
    scores = x @ v.T
    pos = scores.diag()
    valid = groups[:, None] != groups[None, :]
    same_text = (bow[:, None, :] == bow[None, :, :]).all(-1)
    valid &= ~same_text
    loss = F.relu(margin + scores - pos[:, None]) + F.relu(margin + scores - pos[None, :])
    return (loss * valid).sum() / valid.sum().clamp_min(1)

class ConceptHead(nn.Module):
    def __init__(self, dim, n):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(dim, 128), nn.ReLU(), nn.Linear(128, n))

    def forward(self, x):
        return self.layers(x)
