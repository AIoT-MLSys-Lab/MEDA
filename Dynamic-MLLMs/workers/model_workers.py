from workers.baseworker import *
import sys
from PIL import Image
import torch
import re
from .memory import *
set_memory_list()
######################## Multi-image application ########################

class LLaVA(BaseWorker):
    def init_components(self, config):
        sys.path.insert(0, '/users/PAS2473/brucewan666/Dynamic-MLLMs/LLaVA-mix_merge_v1')
        from llava.model.builder import load_pretrained_model
        from llava.conversation import conv_templates, SeparatorStyle
        from llava.constants import DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
        from llava.model.kv_token_merge.modify_llama import H2OLlamaAttention_drop, \
                                                            WeightedLlamaAttention_drop, \
                                                            PivotMergeLlamaAttention_drop, \
                                                            TextH2OLlamaAttention_drop, \
                                                            TextWeightedLlamaAttention_drop, \
                                                            TextPivotLlamaAttention_drop, \
                                                            PoolingWindowLlamaAttention_drop, \
                                                            AVGMergeLlamaAttention_drop, \
                                                            MeanH2OLlamaAttention_drop, \
                                                            TextAVGMergeLlamaAttention_drop, AttnEntropyTextAVGMergeLlamaAttention_drop
                                                            
        self.tokenizer, self.model, self.processor, context_len = load_pretrained_model(
            model_path=config.model_dir,
            model_base=None,
            model_name=config.model_dir,
            device_map='cuda',
            kv_mode=config.kv_mode,
            hh_ratio=config.hh_ratio,
            recent_ratio=config.recent_ratio,
        )
        self.kv_mode = config.kv_mode
        if getattr(self.model.config, 'mm_use_im_start_end', False):
            self.single_img_tokens = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN
        else:
            self.single_img_tokens = DEFAULT_IMAGE_TOKEN

        self.conv_temp = conv_templates["llava_llama_2"]
        stop_str = self.conv_temp.sep if self.conv_temp.sep_style != SeparatorStyle.TWO else self.conv_temp.sep2
        self.keywords = [stop_str]

        self.model.eval()
        choices=["origin", "h2o", "weighted_merge", "pivot_merge", "text_prior_h2o", "text_prior_weighted_merge", "text_prior_pivot_merge"]
        self.TAGET_MODULE = {
            "llama": None,
            "origin": None,
            "h2o": H2OLlamaAttention_drop,
            "weighted_merge": WeightedLlamaAttention_drop,
            "pivot_merge": PivotMergeLlamaAttention_drop,
            "text_prior_h2o": TextH2OLlamaAttention_drop,
            "text_prior_weighted_merge": TextWeightedLlamaAttention_drop,
            "text_prior_pivot_merge": TextPivotLlamaAttention_drop,
            "snapkv": PoolingWindowLlamaAttention_drop,
            "avg_merge": AVGMergeLlamaAttention_drop,
            "mean_h2o": MeanH2OLlamaAttention_drop,
            "text_prior_avg_merge": TextAVGMergeLlamaAttention_drop,
            "attn_entropy_TextAVGMerge": AttnEntropyTextAVGMergeLlamaAttention_drop
        }

    def clean_cache(self):
        if self.kv_mode == "origin":
            return
        for name, m in self.model.named_modules():
            if isinstance(m, self.TAGET_MODULE[self.kv_mode]):
                # breakpoint()
                m._clean_cache()
        

        ##### clean and reset the dynamic cache size ####################

        num_layers = len(self.model.module.model.layers)

        for layer_idx in range(num_layers):

            self.model.module.model.layers[layer_idx].self_attn.layer_hh_ratio = 0
            self.model.module.model.layers[layer_idx].self_attn.layer_recent_ratio = 0

            self.model.module.model.layers[layer_idx].self_attn.multimodal_entropy = 0

            self.model.module.model.layers[layer_idx].self_attn.prfill_size = 0

            self.model.module.model.layers[layer_idx].self_attn.prfill_score = None






    def forward(self, questions, image_paths, device, gen_kwargs):
        from llava.constants import IMAGE_TOKEN_INDEX
        from llava.mm_utils import process_images, tokenizer_image_token, KeywordsStoppingCriteria

        answers = []
        for question,images_path in zip(questions, image_paths):
            conv = self.conv_temp.copy()
            # Multi-image
            if images_path == []:
                image_tensor = None
            else:
                image_tensor = process_images(
                    [Image.open(image_path).convert('RGB') for image_path in images_path],
                    self.processor, self.model.config
                ).to(device)

            question = question.replace('<ImageHere><ImageHere>', '<ImageHere>\n<ImageHere>\n') # NOTE: handle the special cases in CLEVR-Change dataset
            input_prompt = question.replace('<ImageHere>', self.single_img_tokens)
            # breakpoint()
            # record image numbers
            image_nums = len(re.findall(self.single_img_tokens, input_prompt))
            conv.append_message(conv.roles[0], input_prompt)
            conv.append_message(conv.roles[1], None)
            prompt = conv.get_prompt()
            input_ids = tokenizer_image_token(
                prompt=prompt, 
                tokenizer=self.tokenizer, 
                image_token_index=IMAGE_TOKEN_INDEX, 
                return_tensors='pt'
            ).unsqueeze(0).to(device)

            with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
                output_ids = self.model.generate(
                    input_ids,
                    images=image_tensor,
                    use_cache=True,
                    stopping_criteria=[KeywordsStoppingCriteria(self.keywords, self.tokenizer, input_ids)],
                    **gen_kwargs
                )
                input_lens = int((576 * image_nums + input_ids.shape[1] - 5)*0.35)

                # print('image_nums', image_nums)
                # breakpoint()
                output_lens = output_ids.shape[1] # input       # output           # height      # keyval nums   # Byte  # K     # M   # 
                # print("KV Cache GPU Memory: ", (input_lens*2 + output_lens) / 2 * 2 * 32 * 32 * 128 * 2 / 1024 / 1024 / 1024)
                append_element((input_lens*2 + output_lens) / 2 * 2 * 32 * 32 * 128 * 2 / 1024 / 1024 / 1024)            
                # if get_memory_count() >= 20:
                #     print("20 Itmes Mean KV Cache GPU Memory: ", sum(get_memory_list())/get_memory_count())
                #     breakpoint()

            self.clean_cache()
            answer = self.tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()
            answers.append(answer)

        return answers

class InternVL(BaseWorker):
    def init_components(self, config):
        sys.path.insert(0, '/users/PAS2473/brucewan666/Faster-LLaVA/InternVL/internvl_chat_llava')
        from llava.model.builder import load_pretrained_model
        from llava.conversation import conv_templates, SeparatorStyle
        from llava.constants import DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
        from llava.model.kv_token_merge.modify_llama import H2OLlamaAttention_drop, \
                                                            WeightedLlamaAttention_drop, \
                                                            PivotMergeLlamaAttention_drop, \
                                                            TextH2OLlamaAttention_drop, \
                                                            TextWeightedLlamaAttention_drop, \
                                                            TextPivotLlamaAttention_drop, \
                                                            PoolingWindowLlamaAttention_drop, \
                                                            AVGMergeLlamaAttention_drop, \
                                                            MeanH2OLlamaAttention_drop
        self.tokenizer, self.model, self.processor, context_len = load_pretrained_model(
            model_path=config.model_dir,
            model_base=None,
            model_name=config.model_dir,
            device_map='cuda',
            kv_mode=config.kv_mode,
            hh_ratio=config.hh_ratio,
            recent_ratio=config.recent_ratio,
        )
        self.kv_mode = config.kv_mode
        if getattr(self.model.config, 'mm_use_im_start_end', False):
            self.single_img_tokens = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN
        else:
            self.single_img_tokens = DEFAULT_IMAGE_TOKEN

        self.conv_temp = conv_templates["internlm2-chat"]
        stop_str = self.conv_temp.sep if self.conv_temp.sep_style != SeparatorStyle.TWO else self.conv_temp.sep2
        self.keywords = [stop_str]

        self.model.eval()
        choices=["origin", "h2o", "weighted_merge", "pivot_merge", "text_prior_h2o", "text_prior_weighted_merge", "text_prior_pivot_merge"]
        self.TAGET_MODULE = {
            "llama": None,
            "origin": None,
            "h2o": H2OLlamaAttention_drop,
            "weighted_merge": WeightedLlamaAttention_drop,
            "pivot_merge": PivotMergeLlamaAttention_drop,
            "text_prior_h2o": TextH2OLlamaAttention_drop,
            "text_prior_weighted_merge": TextWeightedLlamaAttention_drop,
            "text_prior_pivot_merge": TextPivotLlamaAttention_drop,
            "snapkv": PoolingWindowLlamaAttention_drop,
            "avg_merge": AVGMergeLlamaAttention_drop,
            "mean_h2o": MeanH2OLlamaAttention_drop,
        }

    def clean_cache(self):
        if self.kv_mode == "origin":
            return
        for name, m in self.model.module.named_modules():
            if isinstance(m, self.TAGET_MODULE[self.kv_mode]):
                m._clean_cache()

    def forward(self, questions, image_paths, device, gen_kwargs):
        from llava.constants import IMAGE_TOKEN_INDEX
        from llava.mm_utils import process_images, tokenizer_image_token, KeywordsStoppingCriteria

        answers = []
        for question,images_path in zip(questions, image_paths):
            conv = self.conv_temp.copy()

            # Multi-image
            if images_path == []:
                image_tensor = None
            else:
                image_tensor = process_images(
                    [Image.open(image_path).convert('RGB') for image_path in images_path],
                    self.processor, self.model.config
                ).to(device)

            question = question.replace('<ImageHere><ImageHere>', '<ImageHere>\n<ImageHere>\n') # NOTE: handle the special cases in CLEVR-Change dataset
            input_prompt = question.replace('<ImageHere>', self.single_img_tokens)

            conv.append_message(conv.roles[0], input_prompt)
            conv.append_message(conv.roles[1], None)
            prompt = conv.get_prompt()
            input_ids = tokenizer_image_token(
                prompt=prompt, 
                tokenizer=self.tokenizer, 
                image_token_index=IMAGE_TOKEN_INDEX, 
                return_tensors='pt'
            ).unsqueeze(0).to(device)

            with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
                output_ids = self.model.generate(
                    input_ids,
                    images=image_tensor,
                    use_cache=True,
                    stopping_criteria=[KeywordsStoppingCriteria(self.keywords, self.tokenizer, input_ids)],
                    **gen_kwargs
                )
            self.clean_cache()
            answer = self.tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()
            answers.append(answer)
        return answers

class MobileVLM(BaseWorker):
    def init_components(self, config):
        sys.path.insert(0, '/users/PAS2473/brucewan666/Faster-LLaVA/MobileVLM/mobilevlm')
        
        from model.mobilevlm import load_pretrained_model
        from conversation import conv_templates, SeparatorStyle
        from constants import DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
        from model.kv_token_merge.modify_llama import H2OLlamaAttention_drop, \
                                                            WeightedLlamaAttention_drop, \
                                                            PivotMergeLlamaAttention_drop, \
                                                            TextH2OLlamaAttention_drop, \
                                                            TextWeightedLlamaAttention_drop, \
                                                            TextPivotLlamaAttention_drop, \
                                                            PoolingWindowLlamaAttention_drop, \
                                                            AVGMergeLlamaAttention_drop, \
                                                            MeanH2OLlamaAttention_drop
        self.tokenizer, self.model, self.processor, context_len = load_pretrained_model(
            model_path=config.model_dir,
            device_map='cuda',
            kv_mode=config.kv_mode,
            hh_ratio=config.hh_ratio,
            recent_ratio=config.recent_ratio,
        )
        self.kv_mode = config.kv_mode
        if getattr(self.model.config, 'mm_use_im_start_end', False):
            self.single_img_tokens = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN
        else:
            self.single_img_tokens = DEFAULT_IMAGE_TOKEN

        self.conv_temp = conv_templates["v1"]
        stop_str = self.conv_temp.sep if self.conv_temp.sep_style != SeparatorStyle.TWO else self.conv_temp.sep2
        self.keywords = [stop_str]

        self.model.eval()
        choices=["origin", "h2o", "weighted_merge", "pivot_merge", "text_prior_h2o", "text_prior_weighted_merge", "text_prior_pivot_merge"]
        self.TAGET_MODULE = {
            "llama": None,
            "origin": None,
            "h2o": H2OLlamaAttention_drop,
            "weighted_merge": WeightedLlamaAttention_drop,
            "pivot_merge": PivotMergeLlamaAttention_drop,
            "text_prior_h2o": TextH2OLlamaAttention_drop,
            "text_prior_weighted_merge": TextWeightedLlamaAttention_drop,
            "text_prior_pivot_merge": TextPivotLlamaAttention_drop,
            "snapkv": PoolingWindowLlamaAttention_drop,
            "avg_merge": AVGMergeLlamaAttention_drop,
            "mean_h2o": MeanH2OLlamaAttention_drop,
        }

    def clean_cache(self):
        if self.kv_mode == "origin":
            return
        for name, m in self.model.module.named_modules():
            if isinstance(m, self.TAGET_MODULE[self.kv_mode]):
                m._clean_cache()

    def forward(self, questions, image_paths, device, gen_kwargs):
        sys.path.insert(0, '/users/PAS2473/brucewan666/Faster-LLaVA/MobileVLM')
        from mobilevlm.constants import IMAGE_TOKEN_INDEX
        from mobilevlm.utils import process_images, tokenizer_image_token, KeywordsStoppingCriteria

        answers = []
        for question,images_path in zip(questions, image_paths):
            conv = self.conv_temp.copy()

            # Multi-image
            if images_path == []:
                image_tensor = None
            else:
                image_tensor = process_images(
                    [Image.open(image_path).convert('RGB') for image_path in images_path],
                    self.processor, self.model.config
                ).to(device)

            question = question.replace('<ImageHere><ImageHere>', '<ImageHere>\n<ImageHere>\n') # NOTE: handle the special cases in CLEVR-Change dataset
            input_prompt = question.replace('<ImageHere>', self.single_img_tokens)

            conv.append_message(conv.roles[0], input_prompt)
            conv.append_message(conv.roles[1], None)
            prompt = conv.get_prompt()
            input_ids = tokenizer_image_token(
                prompt=prompt, 
                tokenizer=self.tokenizer, 
                image_token_index=IMAGE_TOKEN_INDEX, 
                return_tensors='pt'
            ).unsqueeze(0).to(device)

            with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
                output_ids = self.model.generate(
                    input_ids,
                    images=image_tensor,
                    use_cache=True,
                    stopping_criteria=[KeywordsStoppingCriteria(self.keywords, self.tokenizer, input_ids)],
                    **gen_kwargs
                )
            self.clean_cache()
            answer = self.tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()
            answers.append(answer)
        return answers