import gevent
import json
from flask import Flask, render_template, jsonify, request

from cnvannot.annotations.dgv import dgv_full_load, dgv_gold_load
from cnvannot.annotations.encode import encode_load
from cnvannot.annotations.omim import omim_morbid_genes_load
from cnvannot.annotations.refseq import refseq_load
from cnvannot.annotations.special.france_incomplete_penetrance import france_incomplete_penetrance_load
from cnvannot.annotations.ucsc import ucsc_get_annotation_link
from cnvannot.annotations.xcnv import *
from cnvannot.common.coordinates import coordinates_from_string
from cnvannot.queries.basic_queries import *
from cnvannot.queries.interpretation import interpretation_get
from cnvannot.queries.specific_queries import dgv_gold_overlap_count_1_percent, exc_overlaps_70_percent, \
    omim_match_organ, dgv_gold_fully_included

app = Flask(__name__)

dgv_full_db = dgv_full_load()
dgv_db = dgv_gold_load()
refseq_db = refseq_load()
omim_mg_db = omim_morbid_genes_load()
encode_db = encode_load()
france_inc_pen_db = france_incomplete_penetrance_load()
xcnv_avail = xcnv_is_avail()


@app.route("/", methods=['GET'])
def main_page():
    return render_template('home.html')


@app.route("/useful_links", methods=['GET'])
def useful_links():
    return render_template('links.html')


@app.route("/about", methods=['GET'])
def about():
    return render_template('about.html')


@app.route("/batch", methods=['GET'])
def batch():
    return render_template('batch.html')


def common_batch(ref, lines, organ):
    queries = []
    for line in lines:
        queries.append(coordinates_from_string(line))

    # X-CNV
    xcnv_res = []
    if ref == 'hg19':
        xcnv_res = xcnv_predict(queries)

    # OTHERS
    ucsc_res = []
    dgv_res = []
    cnv_len_res = []
    cnv_type_res = []
    exc_res = []
    gene_overlap_res = []
    omim_morbid_overlap_res = []
    interpretation_res = []
    for i in range(len(queries)):
        ucsc_res.append(ucsc_get_annotation_link(queries[i]))

        dgv_over = dgv_gold_overlap_count_1_percent(dgv_db, queries[i])
        dgv_res.append(dgv_over)

        cn_len = queries[i].end - queries[i].start
        cnv_len_res.append(f'{cn_len:,}')

        cn_type = str.upper(queries[i].type)
        cnv_type_res.append(cn_type)

        exc_over = exc_overlaps_70_percent(encode_db, queries[i])
        exc_res.append(exc_over)

        g_over = query_overlap_count(refseq_db, queries[i])
        gene_overlap_res.append(g_over)

        m_over = query_overlap_count(omim_mg_db, queries[i])
        omim_morbid_overlap_res.append(m_over)

        organ_match_count = omim_match_organ(omim_mg_db, queries[i], organ)

        dgv_fully_included_count = dgv_gold_fully_included(dgv_db, queries[i])
        dgv_full_fully_included_count = dgv_gold_fully_included(dgv_full_db, queries[i])

        interpretation_res.append(interpretation_get(queries[i], xcnv_res[i]['xcnv']['prediction'],
                                                     exc_over, g_over, m_over, dgv_over, cn_type, france_inc_pen_db,
                                                     organ_match_count, dgv_fully_included_count,
                                                     dgv_full_fully_included_count))

    res = jsonify(
        {'xcnv': xcnv_res, 'ucsc': ucsc_res, 'dgv': dgv_res, 'len': cnv_len_res, 'type': cnv_type_res, 'exc': exc_res,
         'go': gene_overlap_res, 'mo': omim_morbid_overlap_res, 'interpretation': interpretation_res})

    f = open("cnvprocessed.txt", "w")
    nelem = len(ucsc_res)
    for i in range(nelem):
        f.write(ucsc_res[i]['base']['chr'] + "\t" + str(ucsc_res[i]['base']['start']) + "\t" + str(
            ucsc_res[i]['base']['end'])
                + "\t" + ucsc_res[i]['base']['chr'] + "\t" + cnv_type_res[i] + "\t"
                + interpretation_res[i].replace("\n", " ") + "\t" + str(xcnv_res[i]['xcnv']['prediction']) + "\n")
    f.close()

    return res


@app.route("/batch_text", methods=['POST'])
def batch_text():
    json_data = json.loads(request.data.decode('ascii'))
    ref = json_data['ref']
    lines = json_data['lines'].splitlines()
    lines2 = []
    for line in lines:
        lines2.append(ref + ':' + line)

    return common_batch(ref, lines2, json_data['organ'])


@app.route("/batch_file", methods=['POST'])
def batch_file():
    ref = request.form['ref']
    organ = request.form['organ']
    lines = request.files['file'].read().decode('ascii').splitlines()
    lines2 = []
    for line in lines:
        parts = line.split('\t')
        lines2.append(ref + ':' + parts[0] + ':' + parts[1] + '-' + parts[2] + ':' + parts[3])

    return common_batch(ref, lines2, organ)


@app.route("/search/<str_query>", methods=['POST'])
def search(str_query: str):
    query = coordinates_from_string(str_query)
    organ = request.form['organ']
    ucsc_url = str(ucsc_get_annotation_link(query)['ucsc']['link'])
    cnv_len = f'{(query.end - query.start):,}'
    cnv_type = str.upper(query.type)
    exclude_overlaps = exc_overlaps_70_percent(encode_db, query)
    gene_overlap_count = query_overlap_count(refseq_db, query)
    morbid_gene_overlap_count = query_overlap_count(omim_mg_db, query)
    morbid_gene_ivals = query_overlap_get_data(omim_mg_db, query)
    organ_match_count = omim_match_organ(omim_mg_db, query, organ)
    dgv_gold_cnv_overlap_count = dgv_gold_overlap_count_1_percent(dgv_db, query)
    dgv_fully_included_count = dgv_gold_fully_included(dgv_db, query)
    dgv_full_fully_included_count = dgv_gold_fully_included(dgv_full_db, query)

    xcnv_res = None
    xcnv_res_interpretation = None
    if xcnv_avail:
        xcnv_res = xcnv_predict([query])[0]['xcnv']['prediction']
        xcnv_res_interpretation = xcnv_interpretation_from_score(xcnv_res) + '\n'

    synth_interpretation = 'Interpretation suggestion(s): ' + interpretation_get(query,
                                                                                 xcnv_res,
                                                                                 exclude_overlaps,
                                                                                 gene_overlap_count,
                                                                                 morbid_gene_overlap_count,
                                                                                 dgv_gold_cnv_overlap_count,
                                                                                 query.type,
                                                                                 france_inc_pen_db,
                                                                                 organ_match_count,
                                                                                 dgv_fully_included_count,
                                                                                 dgv_full_fully_included_count
                                                                                 )[0:-68]

    synth_interpretation_no_ai = interpretation_get(query,
                                                    xcnv_res,
                                                    exclude_overlaps,
                                                    gene_overlap_count,
                                                    morbid_gene_overlap_count,
                                                    dgv_gold_cnv_overlap_count,
                                                    query.type,
                                                    france_inc_pen_db,
                                                    organ_match_count,
                                                    dgv_fully_included_count,
                                                    dgv_full_fully_included_count,
                                                    False)[0:-68]

    return jsonify({'chr': query.chr,
                    'start': query.start,
                    'end': query.end,
                    'igv_pos': query.chr + ":" + str(query.start) + "-" + str(query.end),
                    'ucsc_url': ucsc_url,
                    'cnv_len': cnv_len,
                    'cnv_type': cnv_type,
                    'exc_overlaps': exclude_overlaps,
                    'gene_overlap_count': gene_overlap_count,
                    'morbid_genes': morbid_gene_ivals,
                    'morbid_gene_overlap_count': morbid_gene_overlap_count,
                    'morbid_gene_pheno_overlap_count': organ_match_count,
                    'dgv_gold_cnv_overlap_count': dgv_gold_cnv_overlap_count,
                    'dgv_gold_fully_inc_count': dgv_fully_included_count,
                    'dgv_fully_inc_count': dgv_full_fully_included_count,
                    'xcnv_res': xcnv_res,
                    'xcnv_res_interpretation': xcnv_res_interpretation,
                    'synth_interpretation': synth_interpretation,
                    'synth_interpretation_no_ai': synth_interpretation_no_ai})


def run_server():
    # dev server
    # app.run()
    # return

    # gevent (production)
    from gevent.pywsgi import WSGIServer
    http_server = WSGIServer(('', 5000), app)
    print('Server is running on: http://127.0.0.1:5000')
    http_server.serve_forever()
