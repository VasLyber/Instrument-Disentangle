import time
import numpy as np
from sklearn.metrics import roc_auc_score 
from sklearn.metrics import average_precision_score
import multiprocessing
import functools
import h5py 
import librosa
import mir_eval
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '1' # change

def class_F1_R_P(gru, pre, th):
    best = np.zeros(4)
    for t in th:
        tidx = gru==1
        vpred = pre.copy()
        vpred[vpred> t] = 1
        vpred[vpred<=t] = 0
        
        TP = vpred[tidx].sum()
        if TP == 0 :
            continue
        
        P = TP / float(vpred.sum())
        R = TP / float(gru.sum())
        F1 = 2*(P*R)/(R+P)
        
        if F1 > best[1]:
            best = np.array([t, F1, R, P])
    return best

def multi_evl(i, gru, pre, th):
    st = time.time()
    evl_metrics = np.zeros(6)

    if len(th) == 0:
        th = np.arange(0, 1, 0.01)
        evl_metrics[:4] = class_F1_R_P(gru[:,i], pre[:,i], th)
    else:
        evl_metrics[:4] = class_F1_R_P(gru[:,i], pre[:,i], [th[i]])
    
    #evl_metrics[4] = average_precision_score(gru[:,i], pre[:,i])
    evl_metrics[5] = roc_auc_score(gru[:,i], pre[:,i], average='micro')
    return evl_metrics

def evl(gru, pre, va_th=[]):
    num = gru.shape[1]
    print(pre.shape,gru.shape)
    gru = gru.transpose((0,2,1)).reshape((-1,num))
    pre = pre.transpose((0,2,1)).reshape((-1,num))
    st =time.time()
    evl_metrics = np.zeros((pre.shape[-1], 6))

    for i in np.arange(pre.shape[-1]):
        evl_metrics[i] = multi_evl(i, gru=gru, pre=pre, th=va_th)
    
    va_th = evl_metrics[:,0].copy()
    evl_metrics = evl_metrics[:,1:] 
    
    acc = evl_metrics[evl_metrics[:,0]!=-1,:].mean(axis=0) * 100
    
    out = '[%s] mAP:%.1f%% AUC:%.1f%% F1-CB:%.1f%% R-CB:%.1f%% P-CB:%.1f%% time:%.1f'\
            % ('VA', acc[3], acc[4], acc[0], acc[1], acc[2], time.time()-st)
    
    print (out)
    return va_th, evl_metrics, out

def test_pitch(dat, model):
    validation_files = dat.validation_files
    test_set_path = test_path()

    thresh_vals = np.arange(0.1, 1.0, 0.1)
    thresh_scores = {t: [] for t in thresh_vals}
    for npy_file, _ in validation_files:

        file_keys = os.path.basename(npy_file).split('_')[:2]
        label_file = glob.glob(
            os.path.join(
                test_set_path, 'mdb_test',
                "{}*{}.txt".format(file_keys[0], file_keys[1]))
        )[0]

        # generate prediction on numpy file
        predicted_output, input_hcqt = \
            get_single_test_prediction(npy_file, model)

        # load ground truth labels
        ref_times, ref_freqs = \
            mir_eval.io.load_ragged_time_series(label_file)

        for thresh in thresh_vals:
            # get multif0 output from prediction
            est_times, est_freqs = \
                pitch_activations_to_mf0(predicted_output, thresh)

            # get multif0 metrics and append
            scores = mir_eval.multipitch.evaluate(
                ref_times, ref_freqs, est_times, est_freqs)
            thresh_scores[thresh].append(scores['Accuracy'])

    avg_thresh = [np.mean(thresh_scores[t]) for t in thresh_vals]
    best_thresh = thresh_vals[np.argmax(avg_thresh)]
    print("Best Threshold is {}".format(best_thresh))
    print("Best validation accuracy is {}".format(np.max(avg_thresh)))
    print("Validation accuracy at 0.5 is {}".format(np.mean(thresh_scores[0.5])))

    return best_thresh


#pitch
def get_freq_grid():
    freq_grid = librosa.cqt_frequencies(88, 27.5, 12)
    return freq_grid

def get_time_grid(n_time_frames):
    time_grid = librosa.core.frames_to_time(range(n_time_frames), sr=16000, hop_length=512)
    return time_grid

def matrix_to_mirinp(tar,thresh):
    fre = get_freq_grid()
    time = get_time_grid(tar.shape[1])
    idx = np.where(tar > thresh)
    est_freqs = [[] for _ in range(len(time))]
    for f, t in zip(idx[0], idx[1]):
        est_freqs[t].append(fre[f])
    est_freqs = [np.array(lst) for lst in est_freqs]
    return time, est_freqs

def get_threshold(all_tar,all_pred):
    thresh_vals = np.arange(0.1, 1.0, 0.1)
    thresh_scores = {t: [] for t in thresh_vals}
    for idx,(tar, pre) in enumerate(zip(all_tar,all_pred)):
        ref_times, ref_freqs = matrix_to_mirinp(tar,0)
        for thresh in thresh_vals:
            est_times, est_freqs = matrix_to_mirinp(pre,thresh)
            scores = mir_eval.multipitch.evaluate(ref_times, ref_freqs, est_times, est_freqs)
            thresh_scores[thresh].append(scores['Accuracy'])
    avg_thresh = [np.mean(thresh_scores[t]) for t in thresh_vals]
    best_thresh = thresh_vals[np.argmax(avg_thresh)]
    return best_thresh

def eval_score(all_tar,all_pred, thresh):
    acc = []
    prec = []
    rec = []
    error = []
    for idx,(tar, pre) in enumerate(zip(all_tar,all_pred)):
        ref_times, ref_freqs = matrix_to_mirinp(tar,0)
        est_times, est_freqs = matrix_to_mirinp(pre,thresh)
        scores = mir_eval.multipitch.evaluate(ref_times, ref_freqs, est_times, est_freqs)
        if scores['Accuracy']>0:
            acc.append(scores['Accuracy'])
            prec.append(scores['Precision'])
            rec.append(scores['Recall'])
            error.append(scores['Total Error'])

    return np.mean(acc),np.mean(prec),np.mean(rec),np.mean(error)