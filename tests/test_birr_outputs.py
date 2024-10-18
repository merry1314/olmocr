import unittest
import base64
from io import BytesIO
from PIL import Image
from transformers import AutoProcessor

from pdelfin.data.renderpdf import render_pdf_to_base64png
from pdelfin.train.dataprep import (
    prepare_data_for_qwen2_training, build_finetuning_prompt
)
import numpy as np
from tqdm import tqdm
from torch.utils.data import DataLoader
from pdelfin.train.utils import make_dataset
from pdelfin.train.core.config import TrainConfig, DataConfig, SourceConfig

import math

def compute_number_of_image_tokens(
    height: int,
    width: int,
    patch_size: int = 14,
    merge_size: int = 2,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280
) -> int:
    """
    Computes the number of image tokens for a given image height and width.

    Args:
        height (int): Original height of the image in pixels.
        width (int): Original width of the image in pixels.
        patch_size (int, optional): Size of each patch. Defaults to 14.
        merge_size (int, optional): Factor by which patches are merged. Defaults to 2.
        min_pixels (int, optional): Minimum allowed total pixels after resizing. Defaults to 56 * 56.
        max_pixels (int, optional): Maximum allowed total pixels after resizing. Defaults to 14 * 14 * 4 * 1280.

    Returns:
        int: The number of image tokens after processing.
    """
    # Compute the factor used in resizing
    factor = patch_size * merge_size

    # Check constraints on height and width
    if height < factor or width < factor:
        raise ValueError(f"Height ({height}) and width ({width}) must be at least {factor} pixels.")
    if max(height, width) / min(height, width) > 200:
        raise ValueError("The aspect ratio of the image must be less than or equal to 200.")

    # Initial resizing to make dimensions divisible by 'factor'
    h_bar = round(height / factor) * factor
    w_bar = round(width / factor) * factor

    # Adjust dimensions if total pixels exceed max_pixels or are below min_pixels
    total_pixels = h_bar * w_bar
    if total_pixels > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif total_pixels < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor

    # Compute grid dimensions after patching and merging
    grid_height = h_bar // (patch_size * merge_size)
    grid_width = w_bar // (patch_size * merge_size)

    # Calculate the number of image tokens
    num_image_tokens = grid_height * grid_width

    return num_image_tokens


class TestBirrTokenization(unittest.TestCase):

    def testLengthExceeded(self):
        raw_tokens = [4913, 6545, 29021, 3252, 268, 2198, 285, 44813, 8337, 788, 3849, 1335, 13538, 82474, 788, 24, 15, 1335, 285, 5237, 788, 3849, 1335, 285, 29477, 5745, 788, 3849, 1335, 52880, 4326, 3252, 66, 1608, 311, 40368, 4428, 3501, 13, 4220, 37764, 1492, 311, 6083, 279, 1614, 315, 18770, 323, 19256, 311, 892, 582, 1431, 2484, 7110, 77, 1699, 14374, 220, 18, 13, 362, 4903, 315, 37610, 323, 68722, 39793, 1699, 1699, 37175, 264, 34219, 7474, 429, 374, 29130, 3425, 311, 48543, 458, 5041, 311, 90964, 11, 323, 429, 12300, 678, 2326, 315, 279, 12829, 315, 26826, 7481, 518, 279, 67764, 315, 3772, 825, 315, 419, 5567, 7190, 77, 1699, 12, 3070, 62226, 26826, 95518, 576, 7474, 1558, 537, 1414, 6896, 1128, 279, 431, 32365, 2025, 686, 22054, 7110, 77, 12, 3070, 3477, 37120, 26826, 95518, 576, 7474, 1558, 537, 1414, 6896, 1128, 279, 39604, 686, 653, 7110, 77, 12, 3070, 38822, 26826, 95518, 576, 7474, 1558, 537, 1414, 6896, 1246, 279, 3081, 686, 13767, 7110, 77, 1699, 1654, 4880, 9658, 429, 421, 279, 7474, 4045, 82, 311, 48543, 279, 2390, 11, 432, 28833, 1119, 264, 8356, 2783, 5116, 13, 6771, 601, 78064, 279, 3042, 897, 315, 279, 2783, 315, 279, 431, 32365, 5041, 438, 1660, 856, 11192, 13, 576, 7474, 24240, 311, 1414, 3425, 39142, 13653, 2138, 279, 18770, 311, 387, 11537, 11, 476, 537, 7110, 77, 1699, 785, 7474, 686, 8329, 856, 11192, 389, 431, 32365, 11, 323, 432, 686, 387, 35118, 3425, 279, 18770, 686, 12170, 13, 576, 7474, 1558, 537, 1414, 6896, 979, 279, 18770, 686, 12170, 11, 7892, 432, 1558, 9793, 1045, 18927, 429, 279, 18770, 686, 12170, 1573, 264, 5189, 882, 13, 1084, 1221, 12703, 279, 18927, 429, 279, 18770, 686, 17331, 553, 894, 2661, 882, 320, 68, 1302, 2572, 259, 10699, 77, 1699, 22043, 279, 5480, 311, 8329, 856, 11192, 389, 431, 32365, 11, 1052, 374, 26826, 911, 279, 18647, 882, 315, 264, 2799, 29350, 42203, 2884, 7110, 77, 1699, 44500, 11, 7241, 279, 18986, 389, 279, 18770, 11, 304, 419, 1142, 279, 4982, 5426, 19029, 387, 9251, 311, 894, 8284, 712, 1667, 4428, 3516, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387, 738, 369, 9442, 429, 5023, 10797, 518, 5080, 7813, 11, 279, 18770, 686, 537, 387, 17827, 13, 758, 3953, 11, 279, 58232, 16869, 1035, 614, 2567, 429, 264, 4722, 4379, 387]

        processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")

        decoded = processor.tokenizer.decode(raw_tokens)

        print(decoded)
        print(len(raw_tokens))
    
    def testNumberOfImageTokens(self):
        blank_image = Image.new('RGB', (1024, 1024), 'white')
        buffer = BytesIO()
        blank_image.save(buffer, format="PNG")

        processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")


        # Prepare messages
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "image": base64.b64encode(buffer.getvalue()).decode('utf-8')
                    },
                    {"type": "text", "text": build_finetuning_prompt("")},
                ],
            }
        ]
        # Apply chat template to get the text
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        print(text)
        start_token_len = len(processor.tokenizer.encode(text))
        print(start_token_len, " total tokens")

        # Process inputs using processor
        inputs = processor(
            text=[text],
            images=[blank_image],
            padding=True,
            return_tensors="np",
        )

        end_token_len = inputs["input_ids"].shape[1]
        print(end_token_len, " total tokens after image processor expansion") 

        print(end_token_len - start_token_len + 1, " max image tokens")

        print(compute_number_of_image_tokens(1024, 1024))
        