from ..config_parser.dependent_parameters_parser import DependentParametersParser
from ..config_parser.framework_parameters_parser import FrameworkParameters


class TensorFlowParametersParser(DependentParametersParser):
    def parse_parameters(self, curr_test):
        CONFIG_FRAMEWORK_DEPENDENT_TAG = 'FrameworkDependent'
        CONFIG_FRAMEWORK_DEPENDENT_CHANNEL_SWAP_TAG = 'ChannelSwap'
        CONFIG_FRAMEWORK_DEPENDENT_MEAN_TAG = 'Mean'
        CONFIG_FRAMEWORK_DEPENDENT_INPUT_SCALE_TAG = 'InputScale'
        CONFIG_FRAMEWORK_DEPENDENT_INPUT_SHAPE_TAG = 'InputShape'
        CONFIG_FRAMEWORK_DEPENDENT_INPUT_NAME_TAG = 'InputName'
        CONFIG_FRAMEWORK_DEPENDENT_OUTPUT_NAMES_TAG = 'OutputNames'
        CONFIG_FRAMEWORK_DEPENDENT_THREAD_COUNT_TAG = 'ThreadCount'
        CONFIG_FRAMEWORK_DEPENDENT_INTER_OP_PARALLELISM_THREADS_TAG = 'InterOpParallelismThreads'
        CONFIG_FRAMEWORK_DEPENDENT_INTRA_OP_PARALLELISM_THREADS_TAG = 'IntraOpParallelismThreads'
        CONFIG_FRAMEWORK_DEPENDENT_KMP_AFFINITY_TAG = 'KmpAffinity'
        CONFIG_FRAMEWORK_DEPENDENT_USE_XLA_TAG = 'UseXLA'

        dep_parameters_tag = curr_test.getElementsByTagName(CONFIG_FRAMEWORK_DEPENDENT_TAG)[0]

        _channel_swap = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_CHANNEL_SWAP_TAG)[0].firstChild
        _mean = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_MEAN_TAG)[0].firstChild
        _input_scale = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_INPUT_SCALE_TAG)[0].firstChild
        _input_shape = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_INPUT_SHAPE_TAG)[0].firstChild
        _input_name = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_INPUT_NAME_TAG)[0].firstChild
        _output_names = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_OUTPUT_NAMES_TAG)[0].firstChild
        _thread_count = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_THREAD_COUNT_TAG)[0].firstChild
        _inter_op_parallelism_threads = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_INTER_OP_PARALLELISM_THREADS_TAG)[0].firstChild
        _intra_op_parallelism_threads = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_INTRA_OP_PARALLELISM_THREADS_TAG)[0].firstChild
        _kmp_affinity = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_KMP_AFFINITY_TAG)[0].firstChild
        _use_xla = dep_parameters_tag.getElementsByTagName(
            CONFIG_FRAMEWORK_DEPENDENT_USE_XLA_TAG)[0].firstChild

        return TensorFlowParameters(
            channel_swap=_channel_swap.data if _channel_swap else None,
            mean=_mean.data if _mean else None,
            input_scale=_input_scale.data if _input_scale else None,
            input_shape=_input_shape.data if _input_shape else None,
            input_name=_input_name.data if _input_name else None,
            output_names=_output_names.data if _output_names else None,
            thread_count=_thread_count.data if _thread_count else None,
            inter_op_parallelism_threads=_inter_op_parallelism_threads.data if _inter_op_parallelism_threads else None,
            intra_op_parallelism_threads=_intra_op_parallelism_threads.data if _intra_op_parallelism_threads else None,
            kmp_affinity=_kmp_affinity.data if _kmp_affinity else None,
            use_xla=_use_xla.data if _use_xla else None,
        )


class TensorFlowParameters(FrameworkParameters):
    def __init__(self, channel_swap, mean, input_scale, input_shape, input_name, output_names, thread_count,
                 inter_op_parallelism_threads, intra_op_parallelism_threads, kmp_affinity, use_xla):
        self.channel_swap = None
        self.mean = None
        self.input_scale = None
        self.input_shape = None
        self.input_name = None
        self.output_names = None
        self.nthreads = None
        self.num_inter_threads = None
        self.num_intra_threads = None
        self.kmp_affinity = None
        self.use_xla = None

        if self._parameter_is_not_none(channel_swap):
            if self._channel_swap_is_correct(channel_swap):
                self.channel_swap = channel_swap
            else:
                raise ValueError('Channel swap can only take values: list of unique values 0, 1, 2.')
        if self._parameter_is_not_none(mean):
            if self._mean_is_correct(mean):
                self.mean = mean
            else:
                raise ValueError('Mean can only take values: list of 3 float elements.')
        if self._parameter_is_not_none(input_scale):
            if self._float_value_is_correct(input_scale):
                self.input_scale = input_scale
            else:
                raise ValueError('Input scale can only take values: float greater than zero.')
        if self._parameter_is_not_none(input_shape):
            if self._input_shape_is_correct(input_shape):
                self.input_shape = input_shape
            else:
                raise ValueError('Input shape can only take values: list of 3 integer elements greater than zero.')
        if self._parameter_is_not_none(input_name):
            self.input_name = input_name
        if self._parameter_is_not_none(output_names):
            self.output_names = output_names
        if self._parameter_is_not_none(thread_count):
            if self._int_value_is_correct(thread_count):
                self.nthreads = thread_count
            else:
                raise ValueError('Threads count can only take integer value')
        if self._parameter_is_not_none(inter_op_parallelism_threads):
            if self._int_value_is_correct(inter_op_parallelism_threads):
                self.num_inter_threads = inter_op_parallelism_threads
            else:
                raise ValueError('Inter op parallelism threads can only take integer value')
        if self._parameter_is_not_none(intra_op_parallelism_threads):
            if self._int_value_is_correct(intra_op_parallelism_threads):
                self.num_intra_threads = intra_op_parallelism_threads
            else:
                raise ValueError('Intra op parallelism threads can only take integer value')
        if self._parameter_is_not_none(kmp_affinity):
            self.kmp_affinity = kmp_affinity
        if self._parameter_is_not_none(use_xla):
            self.use_xla = use_xla

    def _input_shape_is_correct(self, input_shape):
        shape_check = input_shape.split()
        if len(shape_check) != 3:
            return False
        for i in shape_check:
            if not self._int_value_is_correct(i):
                return False
        return True
