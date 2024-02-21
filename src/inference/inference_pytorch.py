import argparse
import importlib
import json
import re
import sys
import traceback

from functools import partial
from pathlib import Path
from time import time

import torch

import postprocessing_data as pp
import preprocessing_data as prep

from transformer import PyTorchTransformer

from inference_tools.loop_tools import loop_inference, get_exec_time
from io_adapter import IOAdapter
from io_model_wrapper import PyTorchIOModelWrapper
from reporter.report_writer import ReportWriter
from configs.config_utils import prepend_to_path, to_camel_case, get_model_config

sys.path.append(str(Path(__file__).resolve().parents[1].joinpath('utils')))  # noqa: E402
from logger_conf import configure_logger  # noqa: E402

log = configure_logger()

try:
    import torch_tensorrt
except ImportError:
    log.info('No torch_tensorrt module, it is ok')

SCRIPT_DIR = Path(__file__).parent
MODEL_CONFIGS_PATH = Path.joinpath(SCRIPT_DIR, 'configs', 'pytorch_configs')


def cli_argument_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument('-m', '--model',
                        help='Path to PyTorch model with format .pt.',
                        type=str,
                        dest='model')
    parser.add_argument('-w', '--weights',
                        help='Path to file with format .pth with weights of PyTorch model',
                        type=str,
                        default=None,
                        dest='weights')
    parser.add_argument('-mm', '--module',
                        help='Module with model architecture.',
                        default='torchvision.models',
                        type=str,
                        dest='module')
    parser.add_argument('-mn', '--model_name',
                        help='Model name from the module.',
                        required=True,
                        type=str,
                        dest='model_name')
    parser.add_argument('--use_model_config',
                        help='Use model config for inference if it exists',
                        action='store_true')
    parser.add_argument('-i', '--input',
                        help='Path to input data',
                        required=False,
                        type=str,
                        nargs='+',
                        dest='input')
    parser.add_argument('-in', '--input_names',
                        help='Names of the input tensors',
                        required=False,
                        default=None,
                        type=prep.names_arg,
                        dest='input_names')
    parser.add_argument('-is', '--input_shapes',
                        help='Input tensor shapes',
                        default=None,
                        type=str,
                        dest='input_shapes')
    parser.add_argument('--mean',
                        help='Parameter mean',
                        default=None,
                        type=str,
                        dest='mean')
    parser.add_argument('--input_scale',
                        help='Parameter input scale',
                        type=str,
                        dest='input_scale')
    parser.add_argument('--output_names',
                        help='Name of the output tensors.',
                        default='output',
                        type=str,
                        nargs='+',
                        dest='output_names')
    parser.add_argument('-b', '--batch_size',
                        help='Batch size.',
                        default=1,
                        type=int,
                        dest='batch_size')
    parser.add_argument('-l', '--labels',
                        help='Labels mapping file.',
                        default=None,
                        type=str,
                        dest='labels')
    parser.add_argument('-nt', '--number_top',
                        help='Number of top results.',
                        default=5,
                        type=int,
                        dest='number_top')
    parser.add_argument('-t', '--task',
                        help='Task type determines the type of output processing '
                             'method. Available values: feedforward - without'
                             'postprocessing (by default); classification - output'
                             'is a vector of probabilities; text-generation - predicted string;'
                             'text-translation - translated string; speech-to-text - '
                             'output is a recognized text.',
                        choices=['feedforward', 'classification', 'text-to-image', 'named-entity-recognition',
                                 'yolo_v7', 'text-generation', 'batch-text-generation', 'text-translation',
                                 'speech-to-text'],
                        default='feedforward',
                        type=str,
                        dest='task')
    parser.add_argument('-ni', '--number_iter',
                        help='Number of inference iterations.',
                        default=1,
                        type=int,
                        dest='number_iter')
    parser.add_argument('--raw_output',
                        help='Raw output without logs.',
                        default=False,
                        type=bool,
                        dest='raw_output')
    parser.add_argument('-d', '--device',
                        help='Specify the target device to infer on CPU or '
                             'NVIDIA_GPU (CPU by default)',
                        default='CPU',
                        type=str,
                        dest='device')
    parser.add_argument('-nd', '--num_gpu_devices',
                        help='Number of devices to infer on',
                        default=None,
                        type=int,
                        dest='num_gpu_devices')
    parser.add_argument('--model_type',
                        help='Model type for inference',
                        choices=['scripted', 'baseline', None],
                        default=None,
                        type=str,
                        dest='model_type')
    parser.add_argument('--inference_mode',
                        help='Inference mode',
                        default=True,
                        type=bool,
                        dest='inference_mode')
    parser.add_argument('--precision',
                        help='Run model in selected precision',
                        default=None,
                        type=str,
                        dest='precision')
    parser.add_argument('--tensor_rt_precision',
                        help='TensorRT precision FP16, FP32.'
                             ' Applicable only for hosts with NVIDIA GPU and pytorch built with TensorRT support',
                        type=str,
                        default=None,
                        dest='tensor_rt_precision')
    parser.add_argument('--compile_with_backend',
                        help='Use torch API compile method with provided backend. Applicable only for torch >= 2.x',
                        type=str,
                        default=None,
                        dest='compile_with_backend')
    parser.add_argument('--layout',
                        help='Parameter input layout',
                        default=None,
                        type=str,
                        dest='layout')
    parser.add_argument('--input_type',
                        help='Parameter input type',
                        default=None,
                        type=str,
                        dest='input_type')
    parser.add_argument('--report_path',
                        type=Path,
                        default=Path(__file__).parent / 'pytorch_inference_report.json',
                        dest='report_path',
                        help='Path to json benchmark report path, default: ./pytorch_inference_report.json')
    parser.add_argument('--time', required=False, default=0, type=int,
                        dest='time',
                        help='Optional. Time in seconds to execute topology.')
    parser.add_argument('--timeout_overhead', required=False, default=300, type=int,
                        dest='timeout_overhead',
                        help='Optional. Time in seconds added to "time" parameter to construct overall timeout.')
    parser.add_argument('--custom_models_links', required=False, default=None, type=str,
                        dest='custom_models_links',
                        help='Optional. Use custom models sources. Format: model_name_1[url],model_name_2[url]')
    parser.add_argument('--num_inter_threads',
                        help='Number of threads used for parallelism between independent operations',
                        default=None,
                        type=int,
                        dest='num_inter_threads')
    parser.add_argument('--num_intra_threads',
                        help='Number of threads used within an individual op for parallelism',
                        default=None,
                        type=int,
                        dest='num_intra_threads')
    args = parser.parse_args()

    return args


def set_thread_num(num_inter_threads, num_intra_threads):
    def validate(num):
        if num < 0:
            raise ValueError(f'Incorrect thread count: {num}')

    if num_inter_threads:
        validate(num_inter_threads)
        torch.set_num_interop_threads(num_inter_threads)
        log.info(f'The number of threads for inter-op parallelism: {num_inter_threads}')
    if num_intra_threads:
        validate(num_intra_threads)
        torch.set_num_threads(num_intra_threads)
        log.info(f'The number of threads for intra-op parallelism: {num_intra_threads}')


def get_device_to_infer(device):
    log.info('Get device for inference')
    if device == 'CPU':
        log.info(f'Inference will be executed on {device}')

        return torch.device('cpu')
    elif device == 'NVIDIA_GPU':
        log.info(f'Inference will be executed on {device}')

        return torch.device('cuda')
    else:
        log.info(f'The device {device} is not supported')
        raise ValueError('The device is not supported')


def is_gpu_available():
    return torch.cuda.is_available()


def get_torch_version():
    return torch.__version__


def get_tensor_rt_dtype(tensor_rt_precision):
    tensor_rt_dtype = None
    if tensor_rt_precision:
        if tensor_rt_precision == 'FP32':
            tensor_rt_dtype = torch.float
        elif tensor_rt_precision == 'FP16':
            tensor_rt_dtype = torch.half
        else:
            raise ValueError(f'Unknown TensorRT precision {tensor_rt_precision}')
    return tensor_rt_dtype


def load_model_from_module(model_name, module, weights, device):
    log.info(f'Loading model {model_name} from module')
    model_cls = importlib.import_module(module).__getattribute__(model_name)

    if weights is None or weights == '':
        log.info('Loading pretrained model')
        return model_cls(weights=True)
    else:
        log.info(f'Loading model with weights from file {weights}')
        model = model_cls()
        checkpoint = torch.load(weights, map_location=device.lower())
        model.load_state_dict(checkpoint)

        return model


def load_model_from_file(model_path):
    log.info(f'Loading model from path {model_path}')

    file_type = model_path.split('.')[-1]
    supported_extensions = ['pt']
    if file_type not in supported_extensions:
        raise ValueError(f'The file type {file_type} is not supported')

    model = torch.load(model_path)

    return model


def load_model_from_config(model_name, model_config, module, weights, device='cpu', num_gpu_devices=None,
                           precision='FP32', should_be_traced=False, custom_models_links=None):
    with prepend_to_path([str(MODEL_CONFIGS_PATH)]):
        model_obj = importlib.import_module(model_config.stem).__getattribute__(to_camel_case(model_name))
    model_cls = model_obj()
    model_cls.set_model_name(model_name)
    model_cls.set_model_weights(weights=weights, module=module)
    model = model_cls.create_model(device=device, num_gpu_devices=num_gpu_devices, precision=precision,
                                   should_be_traced=should_be_traced, custom_models_links=custom_models_links,
                                   log=log)

    weights = model_cls.weights if model_cls.weights and not model_cls.pretrained else None

    custom_compile_func = model_cls.compile_model if model_cls.use_custom_compile_step else None
    custom_trace_func = model_cls.trace_model if model_cls.use_custom_trace_step else None

    if weights:
        return model(weights=weights), custom_compile_func, custom_trace_func

    if model_cls.pretrained:
        return model, custom_compile_func, custom_trace_func


def compile_model(model, device, model_type, shapes, input_type, tensor_rt_dtype, precision, compile_backend,
                  custom_compile_func, custom_trace_func):
    if model_type == 'baseline':
        log.info('Inference will be executed on baseline model')
    elif model_type == 'scripted':
        log.info('Inference will be executed on scripted model')
        model = torch.jit.script(model)
        if compile_backend:
            raise ValueError('Can`t use torch.compile() with scripted model')
    else:
        raise ValueError(f'Model type {model_type} is not supported for inference')

    model.to(device)

    if precision == 'FP16' and isinstance(model, torch.nn.Module):
        model.half()

    if isinstance(model, torch.nn.Module):
        model.eval()

    if compile_backend:
        torch_version = get_torch_version()
        if not re.match(r'(1.\d)\S+', torch_version):
            mode = 'default'
            log.info(f'Compile model with "{mode}" mode, "{compile_backend}" backend')
            if custom_compile_func:
                model = custom_compile_func(model=model, mode=mode, backend=compile_backend)
            else:
                model = torch.compile(model, mode=mode, backend=compile_backend)
        else:
            raise ValueError('Torch.Compile is only available for PyTorch 2.x versions. '
                             f'Current version: {torch_version}')

    if tensor_rt_dtype is not None:
        log.info(f'Run Torch-TensorRT with {tensor_rt_dtype} precision')
        if is_gpu_available():
            if model_type == 'baseline':
                log.info('Make traced model for Torch-TensorRT')
                if custom_trace_func:
                    model = custom_trace_func(model=model, device=device, shapes=shapes)
                else:
                    input_rand = [torch.rand(shapes[key]).to(device) for key in shapes]
                    if input_type == 'int64':
                        input_rand = [key.int() for key in input_rand]
                    model = torch.jit.trace(model, input_rand)

            if tensor_rt_dtype == torch.half and isinstance(model, torch.nn.Module):
                model.half()

            log.info('Make compiled model for Torch-TensorRT')
            inputs = [torch_tensorrt.Input(shapes[key],
                                           dtype=tensor_rt_dtype if input_type != 'int64' else torch.int)
                      for key in shapes]
            tensor_rt_ts_module = torch_tensorrt.compile(model, inputs=inputs,
                                                         truncate_long_and_double=True,
                                                         enabled_precisions=tensor_rt_dtype)
            return tensor_rt_ts_module
        else:
            raise ValueError('GPU is not available')
    else:
        return model


def get_meaning_tokens_from_batch(generated_output, input_size, dot_token=2):
    """
    LLM's output is shaped like [batch_size, MAX_TEXT_LEN].
    However, when batch_size > 1, every output of the model which is less
    than MAX_TEXT_LENGTH is extended by dot tokens to meet the shape of [1, MAX_TEXT_LEN]
    """
    num_tokens = []
    lengths = []
    for i in range(generated_output.shape[0]):
        length = 1  # All model-generated sentences have dot at the end
        for j in range(generated_output.shape[1]):
            if generated_output[i][j] != dot_token:
                length += 1
        lengths.append(length - input_size)
    num_tokens.extend(lengths)
    return num_tokens


def inference_pytorch(model, num_iterations, task_type, get_slice, input_names, inference_mode, device, test_duration):
    with torch.inference_mode(inference_mode):
        output = None
        audio_sampling_rate = None
        time_infer = []
        num_tokens = []
        audios_lengths = []

        tokenizer = None
        processor = None

        input_size = 0

        if task_type in ['text-generation', 'batch-text-generation']:
            from configs.pytorch_configs.causal_lm_base import create_tokenizer, tokenize

            tokenizer = create_tokenizer(model.name_or_path)
            encodings_dict = tokenize(tokenizer, get_slice())

            if task_type in ['text-generation']:
                input_size = encodings_dict['input_ids'].size(1)
                log.debug(f'Encoded input tokens: {input_size}')
            elif task_type in ['batch-text-generation']:
                from configs.onnx_configs.gpt_2 import MAX_TEXT_LEN
                num_tokens.append(MAX_TEXT_LEN)
        elif task_type in ['named-entity-recognition']:
            from configs.pytorch_configs.bert_base_ner import create_tokenizer

            tokenizer = create_tokenizer()
        elif task_type in ['speech-to-text']:
            from configs.pytorch_configs.speech_to_sequence_base import create_processor, process_audio

            processor = create_processor(model)
            waveform, sampling_rate, audio_length = get_slice()
            audios_lengths.append(audio_length)
            encodings_dict = process_audio(processor, waveform, sampling_rate)
            audio_sampling_rate = processor.feature_extractor.sampling_rate

        if num_iterations == 1:
            if task_type in ['classification', 'feedforward', 'yolo_v7']:
                inputs = [torch.tensor(get_slice()[input_name], device=device) for input_name in input_names]

            t0 = time()

            if task_type in ['classification', 'feedforward']:
                output = torch.nn.functional.softmax(model(*inputs), dim=1).to('cpu')
            elif task_type in ['text-to-image']:
                output = model(prompt=get_slice())
            elif task_type in ['yolo_v7']:
                output = model(*inputs)[0].to('cpu')
            elif task_type in ['text-translation']:
                inputs = get_slice()
                output = model.translate_batch(inputs)
            elif task_type in ['named-entity-recognition']:
                from configs.pytorch_configs.bert_base_ner import tokenize, decode

                tokenized_sentence = tokenize(tokenizer, get_slice())['input_ids'].to(device)

                model_output = model(tokenized_sentence)
                tokens, label_indices = decode(tokenizer, tokenized_sentence, model_output)
                num_tokens.append(len(tokens))

                output = (tokens, label_indices)
            elif task_type in ['text-generation']:
                from configs.pytorch_configs.causal_lm_base import generate, decode

                generated_output = generate(model=model, inputs=encodings_dict, device=device, tokenizer=tokenizer)
                output = decode(tokenizer, generated_output)
                num_tokens.extend(get_meaning_tokens_from_batch(generated_output, input_size, dot_token=2))
                log.info(f'Generated tokens num: {num_tokens}')
            elif task_type in ['batch-text-generation']:
                from configs.onnx_configs.gpt_2 import batch_text_generation, decode

                model_output = batch_text_generation(torch_model=model, tokenizer=tokenizer, device=device,
                                                     encodings_dict=encodings_dict)
                output = decode(tokenizer, model_output)
            elif task_type in ['speech-to-text']:
                from configs.pytorch_configs.speech_to_sequence_base import generate, decode

                generated_output = generate(model=model, inputs=encodings_dict, device=device, processor=processor)
                output = decode(processor, generated_output)
                num_tokens.extend(get_meaning_tokens_from_batch(generated_output, input_size, dot_token=2))
                log.info(f'Generated tokens num: {num_tokens}')

            t1 = time()
            time_infer.append(t1 - t0)
        else:
            # several decorator calls in order to use variables as decorator parameters
            loop_results = loop_inference(num_iterations,
                                          test_duration)(inference_iteration)(device, get_slice, input_names, model,
                                                                              task_type, tokenizer, processor,
                                                                              input_size)
            time_infer = loop_results['time_infer']
            num_tokens = loop_results['num_tokens']
            audios_lengths = loop_results['audios_lengths']
            audio_sampling_rate = loop_results['audio_sampling_rate']
    return output, time_infer, num_tokens, audios_lengths, audio_sampling_rate


@get_exec_time()
def infer_slice(device, inputs, model, input_kwarg_name=None, task_type=None, tokenizer=None):
    if task_type in ['text-translation']:
        infer_func = model.translate_batch
    else:
        infer_func = model

    if input_kwarg_name:
        params = {input_kwarg_name: inputs}
        if tokenizer and task_type not in ['named-entity-recognition']:
            params['tokenizer'] = tokenizer
        res = infer_func(**params)
    else:
        res = infer_func(*inputs)

    if device.type == 'cuda':
        torch.cuda.synchronize()

    return res


def inference_iteration(device, get_slice, input_names, model, task_type, tokenizer=None,
                        processor=None, input_size=0):
    inputs = None
    input_kwarg_name = None

    iter_tokens = None
    audio_length = None
    audio_sampling_rate = None

    if task_type in ['text-generation', 'batch-text-generation']:
        from configs.pytorch_configs.causal_lm_base import tokenize, generate

        inputs = tokenize(tokenizer, get_slice())

    if task_type in ['classification', 'feedforward']:
        inputs = [torch.tensor(get_slice()[input_name], device=device) for input_name in input_names]
    elif task_type in ['named-entity-recognition']:
        from configs.pytorch_configs.bert_base_ner import tokenize

        inputs = tokenize(tokenizer, get_slice())['input_ids'].to(device)
        input_kwarg_name = 'input_ids'
    elif task_type in ['text-generation']:
        model = partial(generate, model=model, device=device)
        input_kwarg_name = 'inputs'
    elif task_type in ['speech-to-text']:
        from configs.pytorch_configs.speech_to_sequence_base import process_audio, generate

        waveform, sampling_rate, audio_length = get_slice()
        inputs = process_audio(processor, waveform, sampling_rate)
        audio_sampling_rate = processor.feature_extractor.sampling_rate
        model = partial(generate, model=model, device=device, processor=processor)
        input_kwarg_name = 'inputs'
    elif task_type in ['batch-text-generation']:
        from configs.onnx_configs.gpt_2 import batch_text_generation

        model = partial(batch_text_generation, torch_model=model, tokenizer=tokenizer, device=device)
        input_kwarg_name = 'encodings_dict'
    elif task_type in ['text-to-image']:
        input_kwarg_name = 'prompt'
        inputs = get_slice()
    elif task_type in ['text-translation']:
        input_kwarg_name = 'txt'
        inputs = get_slice()

    if device.type == 'cuda':
        torch.cuda.synchronize()

    res, exec_time = infer_slice(device, inputs, model, input_kwarg_name, task_type, tokenizer)

    if task_type in ['text-generation', 'speech-to-text']:
        iter_tokens = get_meaning_tokens_from_batch(res, input_size, dot_token=2)
        log.debug(f'Generated tokens num: {iter_tokens}')

    if task_type in ['named-entity-recognition']:
        from configs.pytorch_configs.bert_base_ner import decode

        tokens, _ = decode(tokenizer, inputs, res)
        iter_tokens = len(tokens)

    return {'exec_time': exec_time, 'iter_tokens': iter_tokens, 'audio_length': audio_length,
            'audio_sampling_rate': audio_sampling_rate}


def prepare_output(result, output_names, task_type):
    if (output_names is None) or len(output_names) == 0:
        raise ValueError('The number of output tensors does not match the number of corresponding output names')

    if task_type in ['feedforward']:
        return {}
    elif task_type in ['text-generation', 'batch-text-generation', 'yolo_v7', 'text-translation', 'speech-to-text']:
        return result
    elif task_type in ['named-entity-recognition']:
        from configs.pytorch_configs.bert_base_ner import get_decode_result

        tokens, label_indices = result
        decoded_result = get_decode_result(tokens, label_indices)

        return decoded_result
    elif task_type in ['text-to-image']:
        return result.images
    elif task_type in ['classification']:
        log.info('Converting output tensor to print results')
        return {output_names[0]: result.detach().numpy()}
    else:
        raise ValueError(f'Unsupported task {task_type} to print inference results')


def main():
    args = cli_argument_parser()
    report_writer = ReportWriter()
    report_writer.update_framework_info(name='PyTorch', version=get_torch_version())
    report_writer.update_configuration_setup(batch_size=args.batch_size,
                                             iterations_num=args.number_iter,
                                             target_device=args.device)

    try:
        if args.device == 'NVIDIA_GPU' and args.precision:
            torch.backends.cudnn.benchmark = True
            if args.precision == 'TF32':
                log.info('Use the TensorFloat32 (TF32) tensor cores, available on new NVIDIA GPUs since Ampere')
                torch.backends.cudnn.allow_tf32 = True
                torch.backends.cuda.matmul.allow_tf32 = True
            elif args.precision == 'FP32':
                log.info('Disable TF32')
                torch.backends.cudnn.allow_tf32 = False
                torch.backends.cuda.matmul.allow_tf32 = False
                log.info('Disable FP16 reduction')
                torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
                log.info('Disable BF16 reduction')
                torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = False
            elif args.precision == 'FP16':
                log.info('Enable FP16 reduction')
                torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = True
            elif args.precision == 'BF16':
                log.info('Enable BF16 reduction')
                torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = True

        tensor_rt_dtype = get_tensor_rt_dtype(args.tensor_rt_precision)
        args.input_shapes = prep.parse_input_arg(args.input_shapes, args.input_names)
        model_wrapper = PyTorchIOModelWrapper(args.input_shapes, args.batch_size, tensor_rt_dtype,
                                              args.precision, args.input_type)

        args.mean = prep.parse_input_arg(args.mean, args.input_names)
        args.input_scale = prep.parse_input_arg(args.input_scale, args.input_names)
        args.layout = prep.parse_layout_arg(args.layout, args.input_names)
        data_transformer = PyTorchTransformer(prep.create_dict_for_transformer(args))
        io = IOAdapter.get_io_adapter(args, model_wrapper, data_transformer)

        set_thread_num(args.num_inter_threads, args.num_intra_threads)

        device = get_device_to_infer(args.device)
        custom_compile_func = None
        custom_trace_func = None
        if args.model is not None:
            model_type = 'scripted'
            model = load_model_from_file(args.model)
        else:
            model_type = 'baseline'
            model_config = get_model_config(model_name=args.model_name, configs_path=MODEL_CONFIGS_PATH)

            custom_models_dict = {}
            if args.custom_models_links:
                for item in args.custom_models_links.split(','):
                    model_url_parts = item.split('[')
                    model = model_url_parts[0]
                    url = '['.join(model_url_parts[1:])[:-1]
                    custom_models_dict[model] = url
            if model_config and args.use_model_config:
                model, custom_compile_func, custom_trace_func = load_model_from_config(
                    model_name=args.model_name,
                    model_config=model_config,
                    module=args.module,
                    weights=args.weights,
                    device=device,
                    num_gpu_devices=args.num_gpu_devices,
                    precision=args.precision,
                    should_be_traced=tensor_rt_dtype is not None,
                    custom_models_links=custom_models_dict)
            else:
                model = load_model_from_module(model_name=args.model_name, module=args.module,
                                               weights=args.weights, device=args.device)

        if args.task not in ['text-translation'] and (args.num_gpu_devices is None or args.num_gpu_devices == 1):
            compiled_model = compile_model(model=model, device=device, model_type=model_type,
                                           shapes=args.input_shapes, input_type=args.input_type,
                                           tensor_rt_dtype=tensor_rt_dtype,
                                           precision=args.precision,
                                           compile_backend=args.compile_with_backend,
                                           custom_compile_func=custom_compile_func,
                                           custom_trace_func=custom_trace_func)
        else:
            compiled_model = model

        if args.task in ['classification', 'feedforward']:
            for layer_name in args.input_names:
                layer_shape = model_wrapper.get_input_layer_shape(args.model, layer_name)
                log.info(f'Shape for input layer {layer_name}: {layer_shape}')

        if args.input:
            log.info(f'Preparing input data: {args.input}')
            io.prepare_input(compiled_model, args.input)
        else:
            io.fill_unset_inputs(compiled_model, log)

        log.info(f'Starting inference (max {args.number_iter} iterations or {args.time} sec) on {args.device}')
        result, inference_time, num_tokens, audios_lengths, audio_sampling_rate = inference_pytorch(
            model=compiled_model,
            num_iterations=args.number_iter,
            get_slice=io.get_slice_input,
            input_names=args.input_names,
            inference_mode=args.inference_mode,
            device=device, test_duration=args.time,
            task_type=args.task,
        )

        log.info('Computing performance metrics')
        inference_result = pp.calculate_performance_metrics_sync_mode(args.batch_size, inference_time,
                                                                      num_tokens=num_tokens,
                                                                      audios_lengths=audios_lengths,
                                                                      audio_sampling_rate=audio_sampling_rate)
        report_writer.update_execution_results(**inference_result)

        log.info(f'Write report to {args.report_path}')
        report_writer.write_report(args.report_path)

        if not args.raw_output:
            if args.number_iter == 1:
                try:
                    result = prepare_output(result, args.output_names, args.task)
                    log.info('Inference results')
                    io.process_output(result, log)
                except Exception as ex:
                    log.warning('Error when printing inference results. {0}'.format(str(ex)))

        log.info(f'Performance results:\n{json.dumps(inference_result, indent=4)}')
    except Exception:
        log.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    sys.exit(main() or 0)
