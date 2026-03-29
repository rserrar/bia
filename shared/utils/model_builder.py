import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf
from tensorflow.keras import Model, initializers, regularizers
from tensorflow.keras.layers import (
    LSTM,
    Add,
    Activation,
    Attention,
    BatchNormalization,
    Conv1D,
    Dense,
    Dropout,
    Flatten,
    GlobalAveragePooling1D,
    GlobalMaxPooling1D,
    Lambda,
    LayerNormalization,
    MaxPooling1D,
    Multiply,
    MultiHeadAttention,
    Reshape,
    SeparableConv1D,
    SpatialDropout1D,
    concatenate,
    Input,
)


def _get_keras_initializer(
    config_val: Any,
    layer_name_for_debug: str = "",
    model_id_for_debug: str = "",
):
    if isinstance(config_val, str):
        return config_val
    if isinstance(config_val, dict):
        init_type = config_val.get("type")
        init_params = {k: v for k, v in config_val.items() if k != "type"}
        if not init_type:
            print(
                f"WARN (Model '{model_id_for_debug}', Capa '{layer_name_for_debug}'): "
                f"Inicialitzador sense 'type': {config_val}. S'ignorarà."
            )
            return None
        try:
            initializer_class = getattr(initializers, init_type)
            return initializer_class(**init_params)
        except AttributeError:
            raise ValueError(
                f"Model '{model_id_for_debug}', Capa '{layer_name_for_debug}': "
                f"Tipus d'inicialitzador '{init_type}' no reconegut."
            )
        except Exception as error:
            raise ValueError(
                f"Model '{model_id_for_debug}', Capa '{layer_name_for_debug}': "
                f"Error creant inicialitzador '{init_type}' amb paràmetres {init_params}. Detall: {error}"
            )
    if config_val is None:
        return None
    raise ValueError(
        f"Model '{model_id_for_debug}', Capa '{layer_name_for_debug}': "
        f"Format d'inicialitzador invàlid: {config_val}"
    )


def _create_keras_layer(
    layer_config: dict[str, Any],
    current_branch_input_tensor,
    all_processed_maps: dict[str, Any],
    model_id_for_debug: str = "",
):
    layer_type = layer_config.get("type")
    layer_name = layer_config.get("name")
    layer_type_label = str(layer_type or "unknown")

    if not layer_name:
        layer_name = f"{layer_type_label.lower()}_{str(uuid.uuid4())[:8]}"
        print(
            f"ALERTA (Model '{model_id_for_debug}'): Capa de tipus '{layer_type_label}' "
            f"sense nom. Assignat: '{layer_name}'."
        )
        layer_config["name"] = layer_name

    input_tensor_for_this_layer = current_branch_input_tensor
    explicit_input_source = layer_config.get("explicit_input_source_feature_map")
    if explicit_input_source:
        if explicit_input_source not in all_processed_maps:
            raise ValueError(
                f"Model '{model_id_for_debug}', Capa '{layer_name}': "
                f"Font explícita '{explicit_input_source}' no trobada."
            )
        input_tensor_for_this_layer = all_processed_maps[explicit_input_source]

    if layer_type in ["Add", "Multiply"]:
        source_map_names = layer_config.get("input_source_feature_maps")
        if not source_map_names or not isinstance(source_map_names, list) or len(source_map_names) < 2:
            raise ValueError(
                f"Capa '{layer_name}' ({layer_type}): "
                f"Requereix 'input_source_feature_maps' (llista >= 2)."
            )
        input_tensors_for_layer = [
            all_processed_maps[map_name] for map_name in source_map_names if map_name in all_processed_maps
        ]
        if len(input_tensors_for_layer) != len(source_map_names):
            raise ValueError(
                f"Capa '{layer_name}': Algun mapa de 'input_source_feature_maps' no trobat."
            )
        if layer_type == "Add":
            return Add(name=layer_name)(input_tensors_for_layer)
        if layer_type == "Multiply":
            return Multiply(name=layer_name)(input_tensors_for_layer)

    elif layer_type == "AttentionKeras":
        source_map_names = layer_config.get("input_source_feature_maps")
        if not source_map_names or not isinstance(source_map_names, list) or not (2 <= len(source_map_names) <= 3):
            raise ValueError(
                f"Capa '{layer_name}' (AttentionKeras): "
                f"'input_source_feature_maps' ha de ser llista de 2 o 3 noms."
            )
        input_tensors_for_attention = []
        for map_name in source_map_names:
            if map_name not in all_processed_maps:
                raise ValueError(f"Capa '{layer_name}': Mapa '{map_name}' per a AttentionKeras no trobat.")
            input_tensors_for_attention.append(all_processed_maps[map_name])
        params_json = layer_config.get("params", {})
        constructor_params = {"dropout": params_json.get("dropout", 0.0)}
        call_params = {"use_causal_mask": params_json.get("use_causal_mask", False)}
        if "score_mode" in params_json:
            print(f"INFO (AttentionKeras '{layer_name}'): 'score_mode' és informatiu.")
        if "units" in params_json:
            print(f"WARN (AttentionKeras '{layer_name}'): 'units' s'ignora per tf.keras.layers.Attention.")
        attn_layer = Attention(name=f"{layer_name}_internal_op", **constructor_params)
        attn_output = attn_layer(inputs=input_tensors_for_attention, **call_params)

        def _passthrough(x):
            return x

        return Lambda(_passthrough, name=layer_name)(attn_output)

    elif layer_type == "MultiHeadAttentionKeras":
        source_map_names = layer_config.get("input_source_feature_maps")
        if not source_map_names or not isinstance(source_map_names, list) or not (1 <= len(source_map_names) <= 3):
            raise ValueError(
                f"Capa '{layer_name}' (MHA): 'input_source_feature_maps' ha de ser llista de 1-3 noms."
            )
        query_t = None
        value_t = None
        key_t = None
        if len(source_map_names) == 1:
            map_name = source_map_names[0]
            if map_name not in all_processed_maps:
                raise ValueError(f"MHA '{layer_name}': font '{map_name}' no trobada.")
            query_t = value_t = key_t = all_processed_maps[map_name]
        elif len(source_map_names) >= 2:
            q_map_name, v_map_name = source_map_names[0], source_map_names[1]
            if q_map_name not in all_processed_maps:
                raise ValueError(f"MHA '{layer_name}': font query '{q_map_name}' no trobada.")
            if v_map_name not in all_processed_maps:
                raise ValueError(f"MHA '{layer_name}': font value '{v_map_name}' no trobada.")
            query_t, value_t = all_processed_maps[q_map_name], all_processed_maps[v_map_name]
            if len(source_map_names) == 3:
                k_map_name = source_map_names[2]
                if k_map_name not in all_processed_maps:
                    raise ValueError(f"MHA '{layer_name}': font key '{k_map_name}' no trobada.")
                key_t = all_processed_maps[k_map_name]
        constructor_json = layer_config.get("constructor_params", {})
        if "num_heads" not in constructor_json:
            raise ValueError(f"MHA '{layer_name}': 'num_heads' obligatori.")
        if "key_dim" not in constructor_json:
            raise ValueError(f"MHA '{layer_name}': 'key_dim' obligatori.")
        constructor_args = {
            "num_heads": constructor_json["num_heads"],
            "key_dim": constructor_json["key_dim"],
            "value_dim": constructor_json.get("value_dim"),
            "dropout": constructor_json.get("dropout", 0.0),
            "use_bias": constructor_json.get("use_bias", True),
            "output_shape": tuple(constructor_json["output_shape"])
            if "output_shape" in constructor_json
            else None,
            "kernel_initializer": _get_keras_initializer(
                constructor_json.get("kernel_initializer"),
                layer_name,
                model_id_for_debug,
            ),
            "bias_initializer": _get_keras_initializer(
                constructor_json.get("bias_initializer"),
                layer_name,
                model_id_for_debug,
            ),
        }
        constructor_args = {k: v for k, v in constructor_args.items() if v is not None}
        call_json = layer_config.get("call_params", {})
        call_args = {
            "use_causal_mask": call_json.get("use_causal_mask", False),
            "return_attention_scores": call_json.get("return_attention_scores", False),
        }
        if "attention_mask" in call_json:
            mask_name = call_json["attention_mask"]
            if mask_name not in all_processed_maps:
                raise ValueError(f"MHA '{layer_name}': màscara '{mask_name}' no trobada.")
            call_args["attention_mask"] = all_processed_maps[mask_name]
        mha_layer = MultiHeadAttention(name=f"{layer_name}_internal_op", **constructor_args)
        mha_call_inputs = {"query": query_t, "value": value_t}
        if key_t is not None:
            mha_call_inputs["key"] = key_t
        mha_output = mha_layer(**mha_call_inputs, **call_args)
        final_tensor = mha_output
        if isinstance(mha_output, tuple) and call_json.get("return_attention_scores"):
            final_tensor = mha_output[0]
            all_processed_maps[f"{layer_name}_scores"] = mha_output[1]

        def _passthrough_mha(x):
            return x

        return Lambda(_passthrough_mha, name=layer_name)(final_tensor)

    elif layer_type == "Dense":
        keras_params = {
            "units": layer_config.get("units", 64),
            "activation": layer_config.get("activation", "relu"),
            "use_bias": layer_config.get("use_bias", True),
            "kernel_initializer": _get_keras_initializer(
                layer_config.get("kernel_initializer"), layer_name, model_id_for_debug
            ),
            "bias_initializer": _get_keras_initializer(
                layer_config.get("bias_initializer"), layer_name, model_id_for_debug
            ),
        }
        kernel_reg_conf = layer_config.get("kernel_regularizer")
        if kernel_reg_conf and kernel_reg_conf.get("type") == "l1_l2":
            keras_params["kernel_regularizer"] = regularizers.l1_l2(
                l1=kernel_reg_conf.get("l1", 0),
                l2=kernel_reg_conf.get("l2", 0),
            )
        bias_reg_conf = layer_config.get("bias_regularizer")
        if bias_reg_conf and bias_reg_conf.get("type") == "l1_l2":
            keras_params["bias_regularizer"] = regularizers.l1_l2(
                l1=bias_reg_conf.get("l1", 0),
                l2=bias_reg_conf.get("l2", 0),
            )
        activity_reg_conf = layer_config.get("activity_regularizer")
        if activity_reg_conf and activity_reg_conf.get("type") == "l1_l2":
            keras_params["activity_regularizer"] = regularizers.l1_l2(
                l1=activity_reg_conf.get("l1", 0),
                l2=activity_reg_conf.get("l2", 0),
            )
        final_params_dense: dict[str, Any] = {}
        for key, value in keras_params.items():
            if key.endswith("_initializer"):
                if value is not None:
                    final_params_dense[key] = value
            else:
                final_params_dense[key] = value
        return Dense(name=layer_name, **final_params_dense)(input_tensor_for_this_layer)

    elif layer_type == "Conv1D":
        keras_params = {
            "filters": layer_config.get("filters", 32),
            "kernel_size": layer_config.get("kernel_size", 3),
            "activation": layer_config.get("activation", "relu"),
            "padding": layer_config.get("padding", "causal"),
            "strides": layer_config.get("strides", 1),
            "dilation_rate": layer_config.get("dilation_rate", 1),
            "use_bias": layer_config.get("use_bias", True),
            "kernel_initializer": _get_keras_initializer(
                layer_config.get("kernel_initializer"), layer_name, model_id_for_debug
            ),
            "bias_initializer": _get_keras_initializer(
                layer_config.get("bias_initializer"), layer_name, model_id_for_debug
            ),
        }
        for param in ["kernel_size", "strides", "dilation_rate"]:
            value = keras_params.get(param)
            if isinstance(value, list) and len(value) == 1:
                keras_params[param] = value[0]
        final_params_conv1d: dict[str, Any] = {}
        for key, value in keras_params.items():
            if key.endswith("_initializer"):
                if value is not None:
                    final_params_conv1d[key] = value
            else:
                final_params_conv1d[key] = value
        return Conv1D(name=layer_name, **final_params_conv1d)(input_tensor_for_this_layer)

    elif layer_type == "SeparableConv1D":
        keras_params = {
            "filters": layer_config.get("filters", 32),
            "kernel_size": layer_config.get("kernel_size", 3),
            "activation": layer_config.get("activation", "relu"),
            "padding": layer_config.get("padding", "causal"),
            "strides": layer_config.get("strides", 1),
            "dilation_rate": layer_config.get("dilation_rate", 1),
            "depth_multiplier": layer_config.get("depth_multiplier", 1),
            "use_bias": layer_config.get("use_bias", True),
            "depthwise_initializer": _get_keras_initializer(
                layer_config.get("depthwise_initializer"), layer_name, model_id_for_debug
            ),
            "pointwise_initializer": _get_keras_initializer(
                layer_config.get("pointwise_initializer"), layer_name, model_id_for_debug
            ),
            "bias_initializer": _get_keras_initializer(
                layer_config.get("bias_initializer"), layer_name, model_id_for_debug
            ),
        }
        for param in ["kernel_size", "strides", "dilation_rate"]:
            value = keras_params.get(param)
            if isinstance(value, list) and len(value) == 1:
                keras_params[param] = value[0]
        final_params_sepconv1d: dict[str, Any] = {}
        for key, value in keras_params.items():
            if key.endswith("_initializer"):
                if value is not None:
                    final_params_sepconv1d[key] = value
            else:
                final_params_sepconv1d[key] = value
        return SeparableConv1D(name=layer_name, **final_params_sepconv1d)(input_tensor_for_this_layer)

    elif layer_type == "Activation":
        activation_function = layer_config.get("activation_function")
        if not activation_function:
            raise ValueError(f"Capa Activation '{layer_name}': 'activation_function' no especificada.")
        return Activation(activation=activation_function, name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "Dropout":
        return Dropout(rate=layer_config.get("rate", 0.2), name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "SpatialDropout1D":
        return SpatialDropout1D(rate=layer_config.get("rate", 0.2), name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "BatchNormalization":
        params = {k: v for k, v in layer_config.items() if k not in ["type", "name", "explicit_input_source_feature_map"]}
        return BatchNormalization(name=layer_name, **params)(input_tensor_for_this_layer)

    elif layer_type == "LayerNormalization":
        params = {k: v for k, v in layer_config.items() if k not in ["type", "name", "explicit_input_source_feature_map"]}
        return LayerNormalization(name=layer_name, **params)(input_tensor_for_this_layer)

    elif layer_type == "Reshape":
        shape = layer_config.get("target_shape")
        if not shape or not isinstance(shape, list):
            raise ValueError(f"Capa Reshape '{layer_name}': 'target_shape' invàlid.")
        return Reshape(target_shape=tuple(shape), name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "LSTM":
        lstm_params = {
            "units": layer_config.get("units", 32),
            "activation": layer_config.get("activation", "tanh"),
            "recurrent_activation": layer_config.get("recurrent_activation", "sigmoid"),
            "return_sequences": layer_config.get("return_sequences", False),
            "use_bias": layer_config.get("use_bias", True),
            "kernel_initializer": _get_keras_initializer(
                layer_config.get("kernel_initializer"), layer_name, model_id_for_debug
            ),
            "recurrent_initializer": _get_keras_initializer(
                layer_config.get("recurrent_initializer"), layer_name, model_id_for_debug
            ),
            "bias_initializer": _get_keras_initializer(
                layer_config.get("bias_initializer"), layer_name, model_id_for_debug
            ),
        }
        final_lstm_params: dict[str, Any] = {}
        for key, value in lstm_params.items():
            if key.endswith("_initializer"):
                if value is not None:
                    final_lstm_params[key] = value
            else:
                final_lstm_params[key] = value
        return LSTM(name=layer_name, **final_lstm_params)(input_tensor_for_this_layer)

    elif layer_type == "MaxPooling1D":
        pool_size = layer_config.get("pool_size", 2)
        if isinstance(pool_size, list) and len(pool_size) == 1:
            pool_size = pool_size[0]
        return MaxPooling1D(pool_size=pool_size, padding=layer_config.get("padding", "valid"), name=layer_name)(
            input_tensor_for_this_layer
        )

    elif layer_type == "GlobalMaxPooling1D":
        return GlobalMaxPooling1D(name=layer_name, keepdims=layer_config.get("keepdims", False))(
            input_tensor_for_this_layer
        )

    elif layer_type == "GlobalAveragePooling1D":
        return GlobalAveragePooling1D(name=layer_name, keepdims=layer_config.get("keepdims", False))(
            input_tensor_for_this_layer
        )

    elif layer_type == "Flatten":
        return Flatten(name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "LambdaSlice":
        slice_cfg = layer_config.get("slice_params")
        if not slice_cfg or not isinstance(slice_cfg, dict):
            raise ValueError(f"LambdaSlice '{layer_name}': 'slice_params' invàlid.")
        slice_obj = slice(slice_cfg.get("start"), slice_cfg.get("end"), slice_cfg.get("step"))
        axis = slice_cfg.get("axis", 1)

        def _slice_fn(x):
            nd = len(x.shape)
            sl_tpl = [slice(None)] * nd
            eff_axis = axis
            if not (0 <= eff_axis < nd if eff_axis >= 0 else -nd <= eff_axis < 0):
                if axis == 0 and nd > 1 and x.shape[0] is None:
                    eff_axis = 1
                if not (0 <= eff_axis < nd if eff_axis >= 0 else -nd <= eff_axis < 0):
                    raise ValueError(
                        f"LambdaSlice '{layer_name}': axis {axis} fora de rang per shape {x.shape}."
                    )
            sl_tpl[eff_axis] = slice_obj
            return x[tuple(sl_tpl)]

        return Lambda(_slice_fn, name=layer_name)(input_tensor_for_this_layer)

    elif layer_type == "Lambda":
        print(f"ALERTA: Lambda genèrica no implementada ({layer_name}).")
        return input_tensor_for_this_layer

    raise ValueError(f"Tipus de capa '{layer_type}' no suportat ({layer_name}).")


def build_model_from_json_definition(model_def_dict: dict[str, Any]) -> Model:
    model_id = model_def_dict.get("model_id", "ID_Desconegut_ModelBuilder")
    print(f"Construint model: {model_id}")
    tf.keras.utils.set_random_seed(model_def_dict.get("seed", 42))
    architecture_def = model_def_dict.get("architecture_definition", {})

    model_inputs_list: list[Any] = []
    processed_feature_maps: dict[str, Any] = {}

    for input_conf in architecture_def.get("used_inputs", []):
        name = input_conf["input_layer_name"]
        shape = tuple(input_conf["shape"])
        keras_layer = Input(shape=shape, name=name)
        model_inputs_list.append(keras_layer)
        processed_feature_maps[name] = keras_layer

    if not model_inputs_list:
        raise ValueError(f"Model '{model_id}': 'used_inputs' no especificat o buit.")

    for branch_conf in architecture_def.get("branches", []):
        branch_name = branch_conf.get("name", f"branch_{str(uuid.uuid4())[:4]}")
        input_source_layer_name = branch_conf["input_source_layer"]
        if input_source_layer_name not in processed_feature_maps:
            raise ValueError(
                f"Model '{model_id}', Branca '{branch_name}': font '{input_source_layer_name}' no definida."
            )
        current_tensor_in_branch = processed_feature_maps[input_source_layer_name]
        for index, layer_def in enumerate(branch_conf.get("layers", [])):
            layer_def["name"] = layer_def.get(
                "name",
                f"{branch_name}_layer_{index}_{layer_def.get('type', 'unknown').lower()}",
            )
            current_tensor_in_branch = _create_keras_layer(
                layer_def,
                current_tensor_in_branch,
                processed_feature_maps,
                model_id_for_debug=model_id,
            )
            processed_feature_maps[layer_def["name"]] = current_tensor_in_branch
        output_feature_map_name_for_branch = branch_conf["output_feature_map_name"]
        processed_feature_maps[output_feature_map_name_for_branch] = current_tensor_in_branch

    for merge_conf in architecture_def.get("merges", []):
        merge_name = merge_conf.get("name", f"merge_{str(uuid.uuid4())[:4]}")
        source_map_names_for_merge = merge_conf["source_feature_maps"]
        merge_type = str(merge_conf.get("type", "concatenate")).strip().lower()
        inputs_to_merge_tensors: list[Any] = []
        for src_name in source_map_names_for_merge:
            if src_name not in processed_feature_maps:
                raise ValueError(
                    f"Model '{model_id}', Merge '{merge_name}': font '{src_name}' no definida."
                )
            inputs_to_merge_tensors.append(processed_feature_maps[src_name])
        if not inputs_to_merge_tensors:
            raise ValueError(
                f"Model '{model_id}', Merge '{merge_name}': no hi ha 'source_feature_maps' vàlids."
            )
        if merge_type == "concatenate":
            if len(inputs_to_merge_tensors) == 1:
                merged_tensor_output = inputs_to_merge_tensors[0]
            else:
                merged_tensor_output = concatenate(inputs_to_merge_tensors, name=f"{merge_name}_op")
        elif merge_type == "add":
            if len(inputs_to_merge_tensors) == 1:
                merged_tensor_output = inputs_to_merge_tensors[0]
            else:
                merged_tensor_output = Add(name=f"{merge_name}_op")(inputs_to_merge_tensors)
        elif merge_type == "multiply":
            if len(inputs_to_merge_tensors) == 1:
                merged_tensor_output = inputs_to_merge_tensors[0]
            else:
                merged_tensor_output = Multiply(name=f"{merge_name}_op")(inputs_to_merge_tensors)
        else:
            raise ValueError(f"Tipus de merge '{merge_type}' no suportat per '{merge_name}'.")
        current_tensor_after_merge = merged_tensor_output
        processed_feature_maps[f"{merge_name}_op_result"] = current_tensor_after_merge
        for index, layer_def in enumerate(merge_conf.get("layers_after_merge", [])):
            layer_def["name"] = layer_def.get(
                "name",
                f"{merge_name}_post_layer_{index}_{layer_def.get('type', 'unknown').lower()}",
            )
            current_tensor_after_merge = _create_keras_layer(
                layer_def,
                current_tensor_after_merge,
                processed_feature_maps,
                model_id_for_debug=model_id,
            )
            processed_feature_maps[layer_def["name"]] = current_tensor_after_merge
        output_feature_map_name_for_merge = merge_conf["output_feature_map_name"]
        processed_feature_maps[output_feature_map_name_for_merge] = current_tensor_after_merge

    model_outputs_list: list[Any] = []
    output_layer_names_ordered: list[str] = []
    all_output_target_configs = model_def_dict.get("output_targets_config_runtime", [])

    for output_head_conf in architecture_def.get("output_heads", []):
        output_keras_name = output_head_conf["output_layer_name"]
        source_map_name_for_head = output_head_conf["source_feature_map"]
        if source_map_name_for_head not in processed_feature_maps:
            raise ValueError(
                f"Model '{model_id}', Sortida '{output_keras_name}': "
                f"font '{source_map_name_for_head}' no definida."
            )
        input_tensor_to_head = processed_feature_maps[source_map_name_for_head]
        target_global_conf = None
        maps_to_target_name_from_json = output_head_conf.get("maps_to_target_config_name")
        if maps_to_target_name_from_json:
            target_global_conf = next(
                (
                    cfg
                    for cfg in all_output_target_configs
                    if cfg.get("target_name") == maps_to_target_name_from_json
                ),
                None,
            )
            if not target_global_conf:
                raise ValueError(
                    f"Model '{model_id}', Sortida '{output_keras_name}': "
                    f"'maps_to_target_config_name' ('{maps_to_target_name_from_json}') no trobat."
                )
        else:
            for cfg in all_output_target_configs:
                if (
                    cfg.get("default_output_layer_name") == output_keras_name
                    or cfg.get("target_name") == output_keras_name
                    or (
                        cfg.get("target_name")
                        and output_keras_name == f"output_{cfg.get('target_name')}"
                    )
                ):
                    target_global_conf = cfg
                    break
        if not target_global_conf:
            raise ValueError(
                f"Model '{model_id}', Sortida '{output_keras_name}': "
                f"No s'ha pogut trobar config de target."
            )
        output_dense_params = {
            "units": output_head_conf.get("units", target_global_conf.get("total_columns")),
            "activation": output_head_conf.get(
                "activation", target_global_conf.get("activation_output_layer", "linear")
            ),
            "use_bias": output_head_conf.get("use_bias", True),
            "kernel_initializer": _get_keras_initializer(
                output_head_conf.get("kernel_initializer"), output_keras_name, model_id
            ),
            "bias_initializer": _get_keras_initializer(
                output_head_conf.get("bias_initializer"), output_keras_name, model_id
            ),
        }
        if output_dense_params["units"] is None:
            raise ValueError(f"Sortida '{output_keras_name}': 'units' no definides.")
        final_output_dense_params: dict[str, Any] = {}
        for key, value in output_dense_params.items():
            if key.endswith("_initializer"):
                if value is not None:
                    final_output_dense_params[key] = value
            else:
                final_output_dense_params[key] = value
        output_layer_tensor = Dense(name=output_keras_name, **final_output_dense_params)(
            input_tensor_to_head
        )
        model_outputs_list.append(output_layer_tensor)
        output_layer_names_ordered.append(output_keras_name)

    if not model_outputs_list:
        raise ValueError(f"Model '{model_id}': 'output_heads' no especificat o buit.")

    model = Model(inputs=model_inputs_list, outputs=model_outputs_list, name=model_id)

    compile_params_json = model_def_dict.get("training_config", {}).get("compile", {})
    optimizer_conf = compile_params_json.get(
        "optimizer",
        {"type": "Nadam", "learning_rate": 0.001},
    )
    lr = optimizer_conf.get("learning_rate", 0.001)
    clipnorm = optimizer_conf.get("clipnorm")
    optimizer_params: dict[str, Any] = {"learning_rate": lr}
    if clipnorm is not None:
        optimizer_params["clipnorm"] = clipnorm
    try:
        optimizer_class = getattr(tf.keras.optimizers, optimizer_conf.get("type"))
        optimizer_instance = optimizer_class(**optimizer_params)
    except (AttributeError, TypeError) as error:
        raise ValueError(
            f"Model '{model_id}': Optimitzador '{optimizer_conf.get('type')}' no suportat. Error: {error}"
        )

    loss_cfg_dict: Any = {}
    loss_w_cfg_dict: Any = {}
    metrics_cfg_dict: Any = {}
    if compile_params_json.get("dynamic_loss_config_source") == "output_targets_config":
        for out_keras_name in output_layer_names_ordered:
            head_conf_for_this_output = next(
                (
                    h
                    for h in architecture_def.get("output_heads", [])
                    if h["output_layer_name"] == out_keras_name
                ),
                None,
            )
            if not head_conf_for_this_output:
                continue
            maps_to_name = head_conf_for_this_output.get("maps_to_target_config_name")
            compile_target_conf = None
            if maps_to_name:
                compile_target_conf = next(
                    (
                        cfg
                        for cfg in all_output_target_configs
                        if cfg.get("target_name") == maps_to_name
                    ),
                    None,
                )
            else:
                for cfg in all_output_target_configs:
                    if (
                        cfg.get("default_output_layer_name") == out_keras_name
                        or cfg.get("target_name") == out_keras_name
                        or (
                            cfg.get("target_name")
                            and out_keras_name == f"output_{cfg.get('target_name')}"
                        )
                    ):
                        compile_target_conf = cfg
                        break
            if compile_target_conf:
                loss_cfg_dict[out_keras_name] = compile_target_conf.get(
                    "loss_function", "mean_squared_error"
                )
                loss_weights_from_model = compile_params_json.get("loss_weights", {})
                if out_keras_name in loss_weights_from_model:
                    loss_w_cfg_dict[out_keras_name] = loss_weights_from_model[out_keras_name]
                elif compile_target_conf.get("loss_weight") is not None:
                    loss_w_cfg_dict[out_keras_name] = compile_target_conf.get("loss_weight")
                metrics = compile_target_conf.get("metrics", [])
                if metrics:
                    metrics_cfg_dict[out_keras_name] = list(metrics)
            else:
                loss_cfg_dict[out_keras_name] = "mean_squared_error"
    else:
        loss_cfg_dict = compile_params_json.get("loss", "mean_squared_error")
        loss_w_cfg_dict = compile_params_json.get("loss_weights")
        metrics_cfg_dict = compile_params_json.get("metrics")

    model.compile(
        optimizer=optimizer_instance,
        loss=loss_cfg_dict,
        loss_weights=loss_w_cfg_dict if loss_w_cfg_dict else None,
        metrics=metrics_cfg_dict if metrics_cfg_dict else None,
    )
    return model


if __name__ == "__main__":
    print("--- Iniciant prova de model_builder (V2) ---")
    project_root = Path(__file__).resolve().parents[3]
    test_models_dir = project_root / "models" / "test"
    test_models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Arrel del projecte (per a proves): {project_root}")
    print(f"Directori de models de test: {test_models_dir}")
    # Aquesta secció només serveix per proves manuals, es pot ignorar en ús normal.
