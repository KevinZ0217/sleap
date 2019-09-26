"""
Code for data augmentation generators that improve model performance
by regularizing models with random variations of data generated from
transformations of labelled ground truth data.
"""

import numpy as np
import attr
import cattr
import keras
import imgaug

from typing import Union, List, Tuple, Callable


@attr.s(auto_attribs=True)
class Augmenter(keras.utils.Sequence):
    """
    The Augmenter class is a keras.utils.Sequence that generates batches of
    augmented training data for both confidence maps and part affinity fields (PAFs).
    It utilizes imgaug transformations of keypoints (the skeleton nodes of an instance)
    and generates the confidence maps and PAFs on the fly from the augmented keypoints.

    Args:
        X: The input images for training. These are the source images to generate
        random augmentations for.
        Y: Optional ground truth output images that correspond to X.
        points: A list of lists of keypoint data for the given frames X. The outer list
        contains contains a list for each frame. Each inner list is for each instance in
        a frame, each element of which is a np.ndarray containing the keypoints of the
        instance.
        datagen: A function to call on the points to generate data from, for example,
        sleap.nn.datagen.generate_pafs_from_points or sleap.nn.datagen.generate_confmaps_from_points
        output_names: A list of output names which will be the keys for dict returned within the
        output value of the batch tuple FIXME: Please help me explain this better Nat!?!?
        batch_size: The number of training examples to generate per batch.
        shuffle_initially: Whether to initially shuffle the data randomly or not.
        rotation: A float or two dimensional tuple expressing the range of rotataion (in degrees)
        augmentations to perform. If rotation is a scalar, it is transformed to (-rotation, +rotation)
        scale: A tuple specifying lower and upper bound of random scaling factors to apply
        to the images when augmenting. If scale is None or scale[0] == scale[1] then scaling
        augmentation will be skipped.

    """

    X: Union[None, np.ndarray]
    Y: Union[None, np.ndarray] = None
    points: Union[None, List[np.ndarray]] = None
    datagen: Union[None, Callable] = None
    output_names: Union[None, List[str]] = None
    batch_size: int = 32
    shuffle_initially: bool = True
    rotation: Union[float, Tuple[float, float]] = (-180.0, 180.0)
    scale: Union[Tuple[float, float], None] = None

    def __attrs_post_init__(self):

        # Setup batching
        all_idx = np.arange(self.num_samples)
        self.batches = np.array_split(
            all_idx, np.ceil(self.num_samples / self.batch_size)
        )

        # Initial shuffling
        if self.shuffle_initially:
            self.shuffle()

        # Setup affine augmentation
        # TODO: translation?
        self.aug_stack = []
        if self.rotation is not None:
            self.rotation = (
                self.rotation
                if isinstance(self.rotation, tuple)
                else (-self.rotation, self.rotation)
            )
            if self.scale is not None and self.scale[0] != self.scale[1]:
                self.scale = (min(self.scale), max(self.scale))
                self.aug_stack.append(
                    imgaug.augmenters.Affine(rotate=self.rotation, scale=self.scale)
                )
            else:
                self.aug_stack.append(imgaug.augmenters.Affine(rotate=self.rotation))

        # TODO: Flips?
        # imgaug.augmenters.Fliplr(0.5)

        # Create augmenter
        self.aug = imgaug.augmenters.Sequential(self.aug_stack)

    @property
    def num_samples(self):
        """
        Get the number of samples (images) in the dataset.

        Returns:
            The number of samples (images) in the dataset.
        """
        return len(self.X)

    @property
    def num_outputs(self):
        """
        The number of outputs generated by the augmentor.

        Returns:
            The number of outputs.
        """
        return 1 if self.output_names is None else len(self.output_names)

    def shuffle(self, batches_only=False):
        """ Index-based shuffling """

        if batches_only:
            # Shuffle batch order
            np.random.shuffle(self.batches)
        else:
            # Re-batch after shuffling
            all_idx = np.arange(self.num_samples)
            np.random.shuffle(all_idx)
            self.batches = np.array_split(
                all_idx, np.ceil(self.num_samples / self.batch_size)
            )

    def __len__(self):
        return len(self.batches)

    def __getitem__(self, batch_idx):
        aug_det = self.aug.to_deterministic()
        idx = self.batches[batch_idx]

        X = self.X[idx].copy()
        X = aug_det.augment_images(X)

        if self.Y is not None:
            Y = self.Y[idx].copy()
            Y = aug_det.augment_images(Y)

        elif self.points is not None:
            # There's no easy way to apply the keypoint augmentation when we have
            # multiple KeypointsOnImage for each image. So instead, we'll take an list
            # with multiple point_arrays, combine these into a single KeypointsOnImage,
            # and then split this back into multiple point_arrays.
            # Note that we need to keep track of the size of each point_array so we
            # can split the KeypointsOnImage properly.

            # Combine each list of point arrays (per frame) to single KeypointsOnImage
            # points: frames -> instances -> point_array
            frames_in_batch = [self.points[i] for i in idx]
            points_per_instance_per_frame = [
                [pa.shape[0] for pa in frame] for frame in frames_in_batch
            ]

            koi_in_frame = []
            for i, frame in enumerate(frames_in_batch):
                if len(frame):
                    koi = imgaug.augmentables.kps.KeypointsOnImage.from_xy_array(
                        np.concatenate(frame), shape=X[i].shape
                    )
                else:
                    koi = imgaug.augmentables.kps.KeypointsOnImage([], shape=X[i].shape)
                koi_in_frame.append(koi)

            # Augment KeypointsOnImage
            aug_per_frame = aug_det.augment_keypoints(koi_in_frame)

            # Split single KeypointsOnImage back into list of point arrays (per frame).
            # i.e., frames -> instances -> point_array

            # First we convert KeypointsOnImage back to combined point_array
            aug_points_in_frames = [koi.to_xy_array() for koi in aug_per_frame]
            # then we split into list of point_arrays.
            split_points = []
            for i, frame in enumerate(aug_points_in_frames):
                frame_point_arrays = []
                offset = 0
                for point_count in points_per_instance_per_frame[i]:
                    inst_points = frame[offset : offset + point_count]
                    frame_point_arrays.append(inst_points)
                    offset += point_count
                split_points.append(frame_point_arrays)

            if self.datagen is not None:
                Y = self.datagen(split_points)
            else:
                Y = split_points

        else:
            # We shouldn't get here
            pass

        if self.output_names is not None:
            Y = {output_name: Y for output_name in self.output_names}

        return (X, Y)

    @staticmethod
    def make_cattr(X=None, Y=None, Points=None):
        aug_cattr = cattr.Converter()

        # When we serialize the augmentor, exlude data fields, we just want to
        # parameters.
        aug_cattr.register_unstructure_hook(
            Augmenter,
            lambda x: attr.asdict(
                x,
                filter=attr.filters.exclude(
                    attr.fields(Augmenter).X,
                    attr.fields(Augmenter).Y,
                    attr.fields(Augmenter).Points,
                ),
            ),
        )

        # We the user needs to unstructure, what images, outputs, and points should
        # they use. We didn't serialize these, just the parameters.
        if X is not None:
            aug_cattr.register_structure_hook(
                Augmenter, lambda x: Augmenter(X=X, Y=Y, Points=Points, **x)
            )

        return aug_cattr


def demo_augmentation():
    from sleap.io.dataset import Labels
    from sleap.nn.datagen import generate_training_data
    from sleap.nn.datagen import (
        generate_confmaps_from_points,
        generate_pafs_from_points,
    )

    data_path = "tests/data/json_format_v1/centered_pair.json"
    labels = Labels.load_json(data_path)

    # Generate raw training data
    skeleton = labels.skeletons[0]
    imgs, points = generate_training_data(
        labels,
        params=dict(scale=1, instance_crop=True, min_crop_size=0, negative_samples=0),
    )
    shape = (imgs.shape[1], imgs.shape[2])

    def datagen_from_points(points):
        #         return generate_pafs_from_points(points, skeleton, shape)
        return generate_confmaps_from_points(points, skeleton, shape)

    # Augment
    aug = Augmenter(X=imgs, points=points, datagen=datagen_from_points, batch_size=80)
    imgs, aug_out = aug[0]

    from sleap.io.video import Video
    from sleap.gui.overlays.confmaps import demo_confmaps
    from sleap.gui.overlays.pafs import demo_pafs
    from PySide2.QtWidgets import QApplication

    # Visualize augmented training data
    vid = Video.from_numpy(imgs * 255)
    app = QApplication([])
    demo_confmaps(aug_out, vid)
    #     demo_pafs(aug_out, vid)
    app.exec_()


def demo_bad_augmentation():
    from sleap.io.dataset import Labels
    from sleap.nn.datagen import generate_images, generate_confidence_maps

    data_path = "tests/data/json_format_v2/centered_pair_predictions.json"
    # data_path = "tests/data/json_format_v2/minimal_instance.json"

    labels = Labels.load_json(data_path)

    labels.labeled_frames = labels.labeled_frames[123:323:10]

    # Generate raw training data
    skeleton = labels.skeletons[0]
    imgs = generate_images(labels)
    confmaps = generate_confidence_maps(labels)

    # Augment
    aug = Augmenter(X=imgs, Y=confmaps, scale=(0.5, 2))
    imgs, confmaps = aug[0]

    from sleap.io.video import Video
    from sleap.gui.overlays.confmaps import demo_confmaps
    from sleap.gui.overlays.pafs import demo_pafs
    from PySide2.QtWidgets import QApplication

    # Visualize augmented training data
    vid = Video.from_numpy(imgs * 255)
    app = QApplication([])
    demo_confmaps(confmaps, vid)
    app.exec_()


if __name__ == "__main__":
    demo_augmentation()

    # import matplotlib.pyplot as plt

    # plt.figure()
    # plt.subplot(1,2,1)
    # plt.imshow(x[0].squeeze(), cmap="gray")

    # plt.subplot(1,2,2)
    # plt.imshow(y[0].max(axis=-1).squeeze(), cmap="gray")

    # plt.show()
