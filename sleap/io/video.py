""" Video reading and writing interfaces for different formats. """

import os
import shutil

import h5py as h5
import cv2
import imgstore
import numpy as np
import attr
import cattr

from typing import Iterable, Union, List


@attr.s(auto_attribs=True, cmp=False)
class HDF5Video:
    """
    Video data stored as 4D datasets in HDF5 files can be imported into
    the sLEAP system with this class.

    Args:
        filename: The name of the HDF5 file where the dataset with video data is stored.
        dataset: The name of the HDF5 dataset where the video data is stored.
        file_h5: The h5.File object that the underlying dataset is stored.
        dataset_h5: The h5.Dataset object that the underlying data is stored.
        input_format: A string value equal to either "channels_last" or "channels_first".
            This specifies whether the underlying video data is stored as:

                * "channels_first": shape = (frames, channels, width, height)
                * "channels_last": shape = (frames, width, height, channels)
        convert_range: Whether we should convert data to [0, 255]-range
    """

    filename: str = attr.ib(default=None)
    dataset: str = attr.ib(default=None)
    input_format: str = attr.ib(default="channels_last")
    convert_range: bool = attr.ib(default=True)

    def __attrs_post_init__(self):

        # Handle cases where the user feeds in h5.File objects instead of filename
        if isinstance(self.filename, h5.File):
            self.__file_h5 = self.filename
            self.filename = self.__file_h5.filename
        elif type(self.filename) is str:
            try:
                self.__file_h5 = h5.File(self.filename, 'r')
            except OSError as ex:
                raise FileNotFoundError(f"Could not find HDF5 file {self.filename}") from ex
        else:
            self.__file_h5 = None

        # Handle the case when h5.Dataset is passed in
        if isinstance(self.dataset, h5.Dataset):
            self.__dataset_h5 = self.dataset
            self.__file_h5 = self.__dataset_h5.file
            self.dataset = self.__dataset_h5.name
        elif self.dataset is not None and type(self.dataset) is str:
            self.__dataset_h5 = self.__file_h5[self.dataset]
        else:
            self.__dataset_h5 = None


    @input_format.validator
    def check(self, attribute, value):
        if value not in ["channels_first", "channels_last"]:
            raise ValueError(f"HDF5Video input_format={value} invalid.")

        if value == "channels_first":
            self.__channel_idx = 1
            self.__width_idx = 2
            self.__height_idx = 3
        else:
            self.__channel_idx = 3
            self.__width_idx = 2
            self.__height_idx = 1

    def matches(self, other):
        """
        Check if attributes match.

        Args:
            other: The instance to compare with.

        Returns:
            True if attributes match, False otherwise
        """
        return self.filename == other.filename and \
               self.dataset == other.dataset and \
               self.convert_range == other.convert_range and \
               self.input_format == other.input_format

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    @property
    def frames(self):
        return self.__dataset_h5.shape[0]

    @property
    def channels(self):
        return self.__dataset_h5.shape[self.__channel_idx]

    @property
    def width(self):
        return self.__dataset_h5.shape[self.__width_idx]

    @property
    def height(self):
        return self.__dataset_h5.shape[self.__height_idx]

    @property
    def dtype(self):
        return self.__dataset_h5.dtype

    def get_frame(self, idx):# -> np.ndarray:
        """
        Get a frame from the underlying HDF5 video data.

        Args:
            idx: The index of the frame to get.

        Returns:
            The numpy.ndarray representing the video frame data.
        """
        frame = self.__dataset_h5[idx]

        if self.input_format == "channels_first":
            frame = np.transpose(frame, (2, 1, 0))

        if self.convert_range and np.max(frame) <= 1.:
            frame = (frame * 255).astype(int)

        return frame


@attr.s(auto_attribs=True, cmp=False)
class MediaVideo:
    """
    Video data stored in traditional media formats readable by FFMPEG can be loaded
    with this class. This class provides bare minimum read only interface on top of
    OpenCV's VideoCapture class.

    Args:
        filename: The name of the file (.mp4, .avi, etc)
        grayscale: Whether the video is grayscale or not. "auto" means detect
        based on first frame.
    """
    filename: str = attr.ib()
    # grayscale: bool = attr.ib(default=None, converter=bool)
    grayscale: bool = attr.ib()
    bgr: bool = attr.ib(default=True)
    _detect_grayscale = False

    @grayscale.default
    def __grayscale_default__(self):
        self._detect_grayscale = True
        return False

    def __attrs_post_init__(self):

        if not os.path.isfile(self.filename):
            raise FileNotFoundError(f"Could not find filename video filename named {self.filename}")

        # Try and open the file either locally in current directory or with full path
        self.__reader = cv2.VideoCapture(self.filename)

        # Lets grab a test frame to help us figure things out about the video
        self.__test_frame = self.get_frame(0, grayscale=False)

        # If the user specified None for grayscale bool, figure it out based on the
        # the first frame of data.
        if self._detect_grayscale is True:
            self.grayscale = bool(np.alltrue(self.__test_frame[..., 0] == self.__test_frame[..., -1]))

    def matches(self, other):
        """
        Check if attributes match.

        Args:
            other: The instance to compare with.

        Returns:
            True if attributes match, False otherwise
        """
        return self.filename == other.filename and \
               self.grayscale == other.grayscale and \
               self.bgr == other.bgr


    @property
    def fps(self):
        return self.__reader.get(cv2.CAP_PROP_FPS)

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    @property
    def frames(self):
        return int(self.__reader.get(cv2.CAP_PROP_FRAME_COUNT))

    @property
    def frames_float(self):
        return self.__reader.get(cv2.CAP_PROP_FRAME_COUNT)

    @property
    def channels(self):
        if self.grayscale:
            return 1
        else:
            return self.__test_frame.shape[2]

    @property
    def width(self):
        return self.__test_frame.shape[1]

    @property
    def height(self):
        return self.__test_frame.shape[0]

    @property
    def dtype(self):
        return self.__test_frame.dtype

    def get_frame(self, idx, grayscale=None):
        if grayscale is None:
            grayscale = self.grayscale

        if self.__reader.get(cv2.CAP_PROP_POS_FRAMES) != idx:
            self.__reader.set(cv2.CAP_PROP_POS_FRAMES, idx)

        ret, frame = self.__reader.read()

        if grayscale:
            frame = frame[...,0][...,None]

        if self.bgr:
            frame = frame[...,::-1]

        return frame


@attr.s(auto_attribs=True, cmp=False)
class NumpyVideo:
    """
    Video data stored as Numpy array.

    Args:
        filename: Either a file to load or a numpy array of the data.

        * numpy data shape: (frames, width, height, channels)
    """
    filename: attr.ib()

    def __attrs_post_init__(self):

        self.__frame_idx = 0
        self.__width_idx = 1
        self.__height_idx = 2
        self.__channel_idx = 3

        # Handle cases where the user feeds in np.array instead of filename
        if isinstance(self.filename, np.ndarray):
            self.__data = self.filename
            self.filename = "Raw Video Data"
        elif type(self.filename) is str:
            try:
                self.__data = np.load(self.filename)
            except OSError as ex:
                raise FileNotFoundError(f"Could not find filename {self.filename}") from ex
        else:
            self.__data = None

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    def matches(self, other):
        """
        Check if attributes match.

        Args:
            other: The instance to comapare with.

        Returns:
            True if attributes match, False otherwise
        """
        return np.all(self.__data == other.__data)

    @property
    def frames(self):
        return self.__data.shape[self.__frame_idx]

    @property
    def channels(self):
        return self.__data.shape[self.__channel_idx]

    @property
    def width(self):
        return self.__data.shape[self.__width_idx]

    @property
    def height(self):
        return self.__data.shape[self.__height_idx]

    @property
    def dtype(self):
        return self.__data.dtype

    def get_frame(self, idx):
        return self.__data[idx]


@attr.s(auto_attribs=True, cmp=False)
class ImgStoreVideo:
    """
    Video data stored as an ImgStore dataset. See: https://github.com/loopbio/imgstore
    This class is just a lightweight wrapper for reading such datasets as videos sources
    for sLEAP.

    Args:
        filename: The name of the file or directory to the imgstore.
        index_by_original: ImgStores are great for storing a collection of frame
        selected frames from an larger video. If the index_by_original is set to
        True than the get_frame function will accept the original frame numbers of
        from original video. If False, then it will accept the frame index from the
        store directly.
    """

    filename: str = attr.ib(default=None)
    index_by_original: bool = attr.ib(default=True)

    def __attrs_post_init__(self):

        # If the filename does not contain metadata.yaml, append it to the filename
        # assuming that this is a directory that contains the imgstore.
        if 'metadata.yaml' not in self.filename:
            self.filename = os.path.join(self.filename, 'metadata.yaml')

        # Make relative path into absolute, ImgStores don't work properly it seems
        # without full paths if we change working directories. Video.fixup_path will
        # fix this later when loading these datasets.
        self.filename = os.path.abspath(self.filename)

        self.__store = None
        self.open()

    # The properties and methods below complete our contract with the
    # higher level Video interface.

    def matches(self, other):
        """
        Check if attributes match.

        Args:
            other: The instance to comapare with.

        Returns:
            True if attributes match, False otherwise
        """
        return self.filename == other.filename and self.index_by_original == other.index_by_original

    @property
    def frames(self):
        return self.__store.frame_count

    @property
    def channels(self):
        if len(self.__img.shape) < 3:
            return 1
        else:
            return self.__img.shape[2]

    @property
    def width(self):
        return self.__img.shape[1]

    @property
    def height(self):
        return self.__img.shape[0]

    @property
    def dtype(self):
        return self.__img.dtype

    def get_frame(self, frame_number) -> np.ndarray:
        """
        Get a frame from the underlying ImgStore video data.

        Args:
            frame_num: The number of the frame to get. If index_by_original is set to True,
            then this number should actually be a frame index withing the imgstore. That is,
            if there are 4 frames in the imgstore, this number shoulde be from 0 to 3.

        Returns:
            The numpy.ndarray representing the video frame data.
        """

        # Check if we need to open the imgstore and do it if needed
        if not self.imgstore:
            self.open()

        if self.index_by_original:
            img, (frame_number, frame_timestamp) = self.__store.get_image(frame_number)
        else:
            img, (frame_number, frame_timestamp) = self.__store.get_image(frame_number=None,
                                                                          frame_index=frame_number)

        # If the frame has one channel, add a singleton channel as it seems other
        # video implementations do this.
        if img.ndim == 2:
            img = img[:, :, None]

        return img

    @property
    def imgstore(self):
        """
        Get the underlying ImgStore object for this Video.

        Returns:
            The imgstore that is backing this video object.
        """
        return self.__store

    def open(self):
        """
        Open the image store if it isn't already open.

        Returns:
            None
        """
        if not self.imgstore:
            # Open the imgstore
            self.__store = imgstore.new_for_filename(self.filename)

            # Read a frame so we can compute shape an such
            self.__img, (frame_number, frame_timestamp) = self.__store.get_next_image()

    def close(self):
        """
        Close the imgstore if it isn't already closed.

        Returns:
            None
        """
        if self.imgstore:
            # Open the imgstore
            self.__store.close()
            self.__store = None


@attr.s(auto_attribs=True, cmp=False)
class Video:
    """
    The top-level interface to any Video data used by sLEAP is represented by
    the :class:`.Video` class. This class provides a common interface for
    various supported video data backends. It provides the bare minimum of
    properties and methods that any video data needs to support in order to
    function with other sLEAP components. This interface currently only supports
    reading of video data, there is no write support. Unless one is creating a new video
    backend, this class should be instantiated from its various class methods
    for different formats. For example:

    >>> video = Video.from_hdf5(filename='test.h5', dataset='box')
    >>> video = Video.from_media(filename='test.mp4')

    Or we can use auto-detection based on filename:

    >>> video = Video.from_filename(filename='test.mp4')

    Args:
        backend: A backend is and object that implements the following basic
        required methods and properties

        * Properties

            * :code:`frames`: The number of frames in the video
            * :code:`channels`: The number of channels in the video (e.g. 1 for grayscale, 3 for RGB)
            * :code:`width`: The width of each frame in pixels
            * :code:`height`: The height of each frame in pixels

        * Methods

            * :code:`get_frame(frame_index: int) -> np.ndarray(shape=(width, height, channels)`:
            Get a single frame from the underlying video data

    """

    backend: Union[HDF5Video, NumpyVideo, MediaVideo, ImgStoreVideo] = attr.ib()

    # Delegate to the backend
    def __getattr__(self, item):
        return getattr(self.backend, item)

    @property
    def num_frames(self) -> int:
        """The number of frames in the video. Just an alias for frames property."""
        return self.frames

    @property
    def shape(self):
        return (self.frames, self.height, self.width, self.channels)

    def __str__(self):
        """ Informal string representation (for print or format) """
        return type(self).__name__ + " ([%d x %d x %d x %d])" % self.shape

    def __len__(self):
        """
        The length of the video should be the number of frames.

        Returns:
            The number of frames in the video.
        """
        return self.frames

    def get_frame(self, idx: int) -> np.ndarray:
        """
        Return a single frame of video from the underlying video data.

        Args:
            idx: The index of the video frame

        Returns:
            The video frame with shape (width, height, channels)
        """
        return self.backend.get_frame(idx)

    def get_frames(self, idxs: Union[int, Iterable[int]]) -> np.ndarray:
        """
        Return a collection of video frames from the underlying video data.

        Args:
            idxs: An iterable object that contains the indices of frames.

        Returns:
            The requested video frames with shape (len(idxs), width, height, channels)
        """
        if np.isscalar(idxs):
            idxs = [idxs,]
        return np.stack([self.get_frame(idx) for idx in idxs], axis=0)

    def __getitem__(self, idxs):
        if isinstance(idxs, slice):
            start, stop, step = idxs.indices(self.num_frames)
            idxs = range(start, stop, step)
        return self.get_frames(idxs)

    @classmethod
    def from_hdf5(cls, dataset: Union[str, h5.Dataset],
                  filename: Union[str, h5.File] = None,
                  input_format: str = "channels_last",
                  convert_range: bool = True):
        """
        Create an instance of a video object from an HDF5 file and dataset. This
        is a helper method that invokes the HDF5Video backend.

        Args:
            dataset: The name of the dataset or and h5.Dataset object. If filename is
            h5.File, dataset must be a str of the dataset name.
            filename: The name of the HDF5 file or and open h5.File object.
            input_format: Whether the data is oriented with "channels_first" or "channels_last"
            convert_range: Whether we should convert data to [0, 255]-range

        Returns:
            A Video object with HDF5Video backend.
        """
        filename = Video.fixup_path(filename)
        backend = HDF5Video(
                    filename=filename,
                    dataset=dataset,
                    input_format=input_format,
                    convert_range=convert_range
                    )
        return cls(backend=backend)

    @classmethod
    def from_numpy(cls, filename, *args, **kwargs):
        """
        Create an instance of a video object from a numpy array.

        Args:
            filename: The numpy array or the name of the file

        Returns:
            A Video object with a NumpyVideo backend
        """
        filename = Video.fixup_path(filename)
        backend = NumpyVideo(filename=filename, *args, **kwargs)
        return cls(backend=backend)

    @classmethod
    def from_media(cls, filename: str, *args, **kwargs):
        """
        Create an instance of a video object from a typical media file (e.g. .mp4, .avi).

        Args:
            filename: The name of the file

        Returns:
            A Video object with a MediaVideo backend
        """
        filename = Video.fixup_path(filename)
        backend = MediaVideo(filename=filename, *args, **kwargs)
        return cls(backend=backend)

    @classmethod
    def from_filename(cls, filename: str, *args, **kwargs):
        """
        Create an instance of a video object from a filename, auto-detecting the backend.

        Args:
            filename: The path to the video filename. Currently supported types are:

            * Media Videos - AVI, MP4, etc. handled by OpenCV directly
            * HDF5 Datasets - .h5 files
            * Numpy Arrays - npy files
            * imgstore datasets - produced by loopbio's Motif recording system. See: https://github.com/loopbio/imgstore.

        Returns:
            A Video object with the detected backend
        """

        filename = Video.fixup_path(filename)

        if filename.lower().endswith(("h5", "hdf5")):
            return cls(backend=HDF5Video(filename=filename, *args, **kwargs))
        elif filename.endswith(("npy")):
            return cls(backend=NumpyVideo(filename=filename, *args, **kwargs))
        elif filename.lower().endswith(("mp4", "avi")):
            return cls(backend=MediaVideo(filename=filename, *args, **kwargs))
        elif os.path.isdir(filename) or "metadata.yaml" in filename:
            return cls(backend=ImgStoreVideo(filename=filename, *args, **kwargs))
        else:
            raise ValueError("Could not detect backend for specified filename.")

    @classmethod
    def imgstore_from_filenames(cls, filenames: list, output_filename: str, *args, **kwargs):
        """Create an imagestore from a list of image files.

        Args:
            filenames: List of filenames for the image files.
            output_filename: Filename for the imagestore to create.

        Returns:
            A `Video` object for the new imagestore.
        """

        # get the image size from the first file
        first_img = cv2.imread(filenames[0], flags=cv2.IMREAD_COLOR)
        img_shape = first_img.shape

        # create the imagestore
        store = imgstore.new_for_format('png',
                    mode='w', basedir=output_filename,
                    imgshape=img_shape)

        # read each frame and write it to the imagestore
        # unfortunately imgstore doesn't let us just add the file
        for i, img_filename in enumerate(filenames):
            img = cv2.imread(img_filename, flags=cv2.IMREAD_COLOR)
            store.add_image(img, i, i)

        store.close()

        # Return an ImgStoreVideo object referencing this new imgstore.
        return cls(backend=ImgStoreVideo(filename=output_filename))

    @classmethod
    def to_numpy(cls, frame_data: np.array, file_name: str):
        np.save(file_name, frame_data, 'w')

    def to_imgstore(self, path,
                    frame_numbers: List[int] = None,
                    format: str = "png",
                    index_by_original: bool = True):
        """
        Read frames from an arbitrary video backend and store them in a loopbio imgstore.
        This should facilitate conversion of any video to a loopbio imgstore.

        Args:
            path: Filename or directory name to store imgstore.
            frame_numbers: A list of frame numbers from the video to save. If None save
            the entire video.
            format: By default it will create a DirectoryImgStore with lossless PNG format.
            Unless the frame_indices = None, in which case, it will default to 'mjpeg/avi'
            format for video.
            index_by_original: ImgStores are great for storing a collection of
            selected frames from an larger video. If the index_by_original is set to
            True than the get_frame function will accept the original frame numbers of
            from original video. If False, then it will accept the frame index from the
            store directly.

        Returns:
            A new Video object that references the imgstore.
        """

        # If the user has not provided a list of frames to store, store them all.
        if frame_numbers is None:
            frame_numbers = range(self.num_frames)

            # We probably don't want to store all the frames as the PNG default,
            # lets use MJPEG by default.
            format = "mjpeg/avi"

        # Delete the imgstore if it already exists.
        if os.path.exists(path):
            if os.path.isfile(path):
                os.remove(path)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

        # If the video is already an imgstore, we just need to copy it
        # if type(self) is ImgStoreVideo:
        #     new_backend = self.backend.copy_to(path)
        #     return self.__class__(backend=new_backend)

        store = imgstore.new_for_format(format,
                                        mode='w', basedir=path,
                                        imgshape=(self.shape[1], self.shape[2], self.shape[3]),
                                        chunksize=1000)

        # Write the JSON for the original video object to the metadata
        # of the imgstore for posterity
        store.add_extra_data(source_sleap_video_obj=Video.cattr().unstructure(self))

        import time
        for frame_num in frame_numbers:
            store.add_image(self.get_frame(frame_num), frame_num, time.time())

        store.close()

        # Return an ImgStoreVideo object referencing this new imgstore.
        return self.__class__(backend=ImgStoreVideo(filename=path, index_by_original=index_by_original))

    @staticmethod
    def cattr():
        """
        Return a cattr converter for serialiazing\deseriializing Video objects.

        Returns:
            A cattr converter.
        """

        # When we are structuring video backends, try to fixup the video file paths
        # in case they are coming from a different computer or the file has been moved.
        def fixup_video(x, cl):
            if 'filename' in x:
                x['filename'] = Video.fixup_path(x['filename'])
            if 'file' in x:
                x['file'] = Video.fixup_path(x['file'])

            return cl(**x)

        vid_cattr = cattr.Converter()

        # Check the type hint for backend and register the video path
        # fixup hook for each type in the Union.
        for t in attr.fields(Video).backend.type.__args__:
            vid_cattr.register_structure_hook(t, fixup_video)

        return vid_cattr

    @staticmethod
    def fixup_path(path) -> str:
        """
        Given a path to a video try to find it. This is attempt to make the paths
        serialized for different video objects portabls across multiple computers.
        The default behaviour is to store whatever path is stored on the backend
        object. If this is an absolute path it is almost certainly wrong when
        transfered when the object is created on another computer. We try to
        find the video by looking in the current working directory as well.

        Args:
            path: The path the video asset.

        Returns:
            The fixed up path
        """

        # If path is not a string then just return it and assume the backend
        # knows what to do with it.
        if type(path) is not str:
            return path

        if os.path.exists(path):
            return path

        # Strip the directory and lets see if the file is in the current working
        # directory.
        elif os.path.exists(os.path.basename(path)):
            return os.path.basename(path)

        # Special case: this is an ImgStore path! We cant use
        # basename because it will strip the directory name off
        elif path.endswith('metadata.yaml'):

            # Get the parent dir of the YAML file.
            img_store_dir = os.path.basename(os.path.split(path)[0])

            if os.path.exists(img_store_dir):
                return img_store_dir

        raise FileNotFoundError(f"Cannot find a video file: {path}")

