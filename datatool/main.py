source          = "bd"
data_path       = "/mnt/sdd/zxr/xlink/{}/".format(source)


"""
0. 生成标准输入
    - entity_id.txt
    - standard_corpus.txt 
        - 每行的格式 <instance_id>\t\t<annotated_document>
        - 每个出现过的 instance_id 必须在词表 entity_id.txt 中
        - annotated_document 的格式有效
            - 括号合法
            - 在 document 中出现过的 instance_id 必须在词表 entity_id.txt 中
            - 对于中文，去掉所有的空格（包括 mention 内部的和 英文单词之间 的）
"""

from utils.entity import EntityHolder
from datatool.pipeline.prepare_standard_input import get_id2title_from_ttl, generate_standard_entity_id, corpus_refine, corpus_annotation_refine

"""
0.1 从 ttl 和 instance_id 得到合法实体集
"""
ttl_path                = data_path + "entity_id.ttl"
standard_entity_id_path = data_path + "entity_id.txt"

id_holder = EntityHolder.get_instance(source)
standard_id2title = get_id2title_from_ttl(ttl_path)
generate_standard_entity_id(source, id_holder, standard_id2title)

"""
0.2 从 raw_corpus.txt 到 refined_corpus.txt
    - raw_corpus.txt        <title>\t\t<sub_title>\t\t<complete_url>\t\t<corpus_text>
    - refined_corpus.txt    <valid_entity_id>\t\t<valid_corpus_text>

refined_corpus.txt 的每条数据满足：
        - 有 abstract/article
        - abstract/article 的标注合法（括号数量匹配且无嵌套） (对于中文数据的处理要先把所有的空格去掉)
        - 有对应的合法 entity id
        
0.3 从 refined_corpus.txt 到 standard_corpus.txt
"""
corpus_name     = "abstract"
raw_corpus_path      = data_path + "raw_{}.txt".format(corpus_name)
refined_corpus_path  = data_path + "refined_{}.txt".format(corpus_name)
standard_corpus_path = data_path + "standard_{}.txt".format(corpus_name)

corpus_refine(source, raw_corpus_path, refined_corpus_path)
corpus_annotation_refine(source, refined_corpus_path, standard_corpus_path)


""" 1. 抽取 mention_anchors 和 out_links """

from datatool.pipeline.extract_mention_anchors import extract_mention_and_out_links_from_corpus
from datatool.pipeline.tools import cal_unique_anchors, cal_valid_out_links, cal_mention_bigger, cal_mention_eq

"""
1.1 从 standard_corpus.txt 抽取 mention_anchors 和 out_links
"""
mention_anchors, out_links = extract_mention_and_out_links_from_corpus(standard_corpus_path)
referred_entities = cal_unique_anchors(mention_anchors)
out_linked_entities = cal_valid_out_links(out_links)
print("Mentions: #{}".format(len(mention_anchors)))
print("Referred Entities: #{}".format(len(referred_entities)))
print("Valid Out_links: #{}".format(len(out_linked_entities)))
print("Candidate=1: #{}".format(cal_mention_eq(mention_anchors, 1)))
print("Candidate>1: #{}".format(cal_mention_bigger(mention_anchors, 1)))


""" 2. 生成训练 word embedding 和 entity embedding 需要的 train_text 和 train_kg """

from datatool.pipeline.extract_embedding_train import extract_bd_corpus, extract_wiki_corpus, generate_train_kg_from_out_links

"""
2.1 从 out_links 生成 train_kg
"""
train_kg_path = data_path + "emb/train_kg_{}.txt".format(corpus_name)
generate_train_kg_from_out_links(out_links, train_kg_path)

"""
2.2 从 standard_corpus.txt 生成 train_text
"""
train_text_path = data_path + "emb/train_text_{}.txt".format(corpus_name)
if source == "bd":
    ma, ol, invalid_lines = extract_bd_corpus(standard_corpus_path, train_text_path)
elif source == "wiki":
    ma, ol, invalid_lines = extract_wiki_corpus(standard_corpus_path, train_text_path)


""" 3. 生成构建字典树需要的文件 """

from datatool.pipeline.generate_trie_dict import expand_mention_anchors, generate_mention_anchors_txt_for_trie, generate_title_entities_txt_for_trie, generate_vocab_word_for_trie


"""
3.1 从 mention_anchors 生成 title_entities，再建字典树
    - mention_anchors -> mention_anchors.trie
    - title_entities  -> title_entities.trie
"""
title_entities = expand_mention_anchors(source, mention_anchors)
mention_anchors_txt_path = data_path + "mention_anchors.txt"
generate_mention_anchors_txt_for_trie(mention_anchors, mention_anchors_txt_path)
title_entities_txt_path  = data_path + "title_entities.txt"
generate_title_entities_txt_for_trie(title_entities, title_entities_txt_path)

"""
3.2 从训 embedding 得到的 vocab_word.txt 生成 word.trie
"""
vocab_word_path = data_path + "emb/result300/vocab_word.txt"
vocab_word_for_trie_path = data_path + "vocab_word.txt"
generate_vocab_word_for_trie(vocab_word_path, vocab_word_for_trie_path)


""" 
4. 生成三个概率文件 
    - baidu_entity_prior.dat        entity::;prior
    - prob_mention_entity.dat       entity::;mention::;prob
    - link_prob.dat                 mention::;entity_id::;link(a)::;freq(a)::;link_prob::;p(e|m)
    
在这一步之前，需要把所有 corpus 的 mention_anchors 都生成并且 expand_entity_titles
"""
from datatool.pipeline.generate_prob_files import cal_4_prob_from_mention_anchors, cal_freq_m, \
    generate_entity_prior_file, generate_link_prob_file, generate_prob_mention_entity_file
from config import Config
from jpype import *


"""
4.1 生成五个有用的统计值
    - entity_prior      p(e)
    - m_given_e         p(m|e)
    - e_given_m         p(e|m)
    - mention_link      link(m)
    - freq_m            freq(m)
"""
# mention_anchors = json.load(open(data_path + "mention_anchors.json"))
entity_prior, m_given_e, e_given_m, mention_link = cal_4_prob_from_mention_anchors(mention_anchors)

jar_path = Config.project_root + "data/jar/BuildIndex.jar"
startJVM(getDefaultJVMPath(), "-Djava.class.path=%s" % jar_path)
JDClass = JClass("edu.TextParser")
mention_anchors_trie_path = data_path + "mention_anchors.trie"
freq_m = cal_freq_m(standard_corpus_path, mention_anchors_txt_path, mention_anchors_trie_path, JDClass)
shutdownJVM()

"""
4.2 根据 freq_m 对 mention_anchors refine
 
有时候得到的 feq_m 与 mention_anchors 的 mentions 不一致，这时需要 refine mention_anchors，并重做 3.1
"""
from datatool.pipeline.generate_prob_files import update_mention_anchor_from_freq_m
mention_anchors = update_mention_anchor_from_freq_m(mention_anchors, freq_m)
title_entities = expand_mention_anchors(source, mention_anchors)
mention_anchors_txt_path = data_path + "mention_anchors.txt"
generate_mention_anchors_txt_for_trie(mention_anchors, mention_anchors_txt_path)
title_entities_txt_path  = data_path + "title_entities.txt"
generate_title_entities_txt_for_trie(title_entities, title_entities_txt_path)

"""
4.3 生成三个目标概率文件
    - baidu_entity_prior.dat        entity::;prior
    - prob_mention_entity.dat       entity::;mention::;prob
    - link_prob.dat                 mention::;entity_id::;link(a)::;freq(a)::;link_prob::;p(e|m)
"""
entity_prior_path = data_path + "entity_prior.dat"
entity_prior_json_path = data_path + "entity_prior.json"
generate_entity_prior_file(entity_prior, entity_prior_path, entity_prior_json_path)

link_prob_path = data_path + "link_prob.dat"
generate_link_prob_file(e_given_m, mention_link, freq_m, link_prob_path)

prob_mention_entity_path = data_path + "prob_mention_entity.dat"
prob_mention_entity_json_path = data_path + "prob_mention_entity.json"
generate_prob_mention_entity_file(m_given_e, prob_mention_entity_path, prob_mention_entity_json_path)