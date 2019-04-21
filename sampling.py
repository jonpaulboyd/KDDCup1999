"""
===========================================================================
Sampling techniques using KDD Cup 1999 IDS dataset
===========================================================================
The following examples demonstrate various sampling techniques for a dataset
in which classes are extremely imbalanced with heavily skewed features
"""
import sys
from contextlib import contextmanager
import time
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import PowerTransformer
from sklearn import preprocessing
from imblearn.over_sampling import RandomOverSampler, ADASYN, SMOTE, BorderlineSMOTE, SVMSMOTE, SMOTENC
from xgboost import XGBClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from collections import OrderedDict
from filehandler import Filehandler
from dataset import KDDCup1999
from visualize import Visualize


@contextmanager
def timer(title):
    t0 = time.time()
    yield
    print('{} - done in {:.0f}s'.format(title, time.time() - t0))


class Original:
    def fit_resample(self, x, y):
        return x, y


class Model:
    def __init__(self):
        self.enabled = False
        self.X_train = None
        self.y_train = None
        self.random_state = 20
        self.predictions = None
        self.base = {'model': None,
                     'stext': None,
                     'scores': None,
                     'cm': None}

    def fit(self, x, y):
        self.base['model'].fit(x, y)

    def predict(self, x, y):
        return cross_val_predict(self.base['model'], x, y, cv=10)


class XgboostClf(Model):
    def __init__(self):
        Model.__init__(self)
        self.base['stext'] = 'XGC'
        self.base['model'] = XGBClassifier(n_estimators=100, random_state=self.random_state)


class Sampling:
    def __init__(self):
        self.logfile = None
        self.gettrace = getattr(sys, 'gettrace', None)
        self.original_stdout = sys.stdout
        self.timestr = time.strftime("%Y%m%d-%H%M%S")
        self.log_file()

        print(__doc__)

        self.filehandler = Filehandler()
        self.ds = KDDCup1999()
        self.visualize = Visualize()
        self.random_state = 20
        self.X = None
        self.y = None
        self.full = None
        self.ac_count = {}
        self.scores = OrderedDict()
        self.scale_cols = ['duration', 'src_bytes', 'dst_bytes', 'land', 'wrong_fragment', 'urgent', 'hot',
                           'num_failed_logins', 'logged_in', 'num_compromised', 'root_shell', 'su_attempted',
                           'num_root', 'num_file_creations', 'num_shells', 'num_access_files', 'is_guest_login',
                           'count', 'srv_count', 'serror_rate', 'rerror_rate', 'diff_srv_rate', 'srv_diff_host_rate',
                           'dst_host_count', 'dst_host_srv_count', 'dst_host_diff_srv_rate',
                           'dst_host_same_src_port_rate', 'dst_host_srv_diff_host_rate']

        with timer('\nLoading dataset'):
            self.load_data()
            self.set_attack_category_count()
        with timer('\nEncode and Scale dataset'):
            # Encode categoricals
            le = preprocessing.LabelEncoder()
            self.full['protocol_type'] = le.fit_transform(self.full['protocol_type'])
            self.full['service'] = le.fit_transform(self.full['service'])
            self.full['flag'] = le.fit_transform(self.full['flag'])

            # Scale
            pt = PowerTransformer(method='yeo-johnson')
            self.full[self.scale_cols] = pt.fit_transform(self.full[self.scale_cols])
        with timer('\nSetting X'):
            self.set_X()
            self.ds.shape()
        with timer('\nScaling'):
            # Sampling options
            for sampler in (Original(),
                            RandomOverSampler(),
                            SMOTE(random_state=0),
                            ADASYN(random_state=self.random_state),
                            BorderlineSMOTE(random_state=self.random_state, kind='borderline-1'),
                            BorderlineSMOTE(random_state=self.random_state, kind='borderline-2'),
                            SVMSMOTE(random_state=self.random_state),
                            SMOTENC(categorical_features=[1, 2, 3], random_state=self.random_state)):

                # JP _ TOP CJHECK _ SETTIMNG OF CORRECT TARGET LABEL AND Y AS WANT TO KEEP LABEL
                label = 'attack_category'
                self.set_y(label)
                res_x, res_y, title = self.sample(sampler)
                self.model_and_score(res_x, res_y, title, label)
                res_x.attack_category.value_counts().plot(kind='bar', title='Re-weighted Count (attack_category)')
                plt.show()

                label = 'target'
                self.set_y(label)
                res_x, res_y, title = self.sample(sampler)
                self.model_and_score(res_x, res_y, title, label)

        self.log_file()
        print('Finished')

    def log_file(self):
        if self.gettrace is None:
            pass
        elif self.gettrace():
            pass
        else:
            if self.logfile:
                sys.stdout = self.original_stdout
                self.logfile.close()
                self.logfile = False
            else:
                # Redirect stdout to file for logging if not in debug mode
                self.logfile = open('logs/{}_{}_stdout.txt'.format(self.__class__.__name__, self.timestr), 'w')
                sys.stdout = self.logfile

    def load_data(self):
        self.ds.dataset = self.filehandler.read_csv(self.ds.config['path'], self.ds.config['file'] + '_processed')
        self.ds.target = self.filehandler.read_csv(self.ds.config['path'], self.ds.config['file'] + '_target')
        self.full = pd.concat([self.ds.dataset, self.ds.target], axis=1)
        self.ds.shape()
        self.ds.row_count_by_target('attack_category')

    def set_attack_category_count(self):
        ac = self.full['attack_category'].value_counts()
        for key, value in ac.items():
            self.ac_count[key] = value

    def set_X(self):
        self.X = self.full.loc[:, self.scale_cols]

    def set_y(self, label):
        self.y = self.full[label]

    def sample(self, sampler):
        title = sampler.__class__.__name__
        res_x, res_y = sampler.fit_resample(self.X, self.y)
        print('Shape after sampling with {} - x {},  y {}'.format(title, res_x.shape, res_y.shape))
        return res_x, res_y, title

    def model_and_score(self, res_x, res_y, title, label):
        clf = XGBClassifier(n_estimators=100, random_state=self.random_state)
        kfold = StratifiedKFold(n_splits=10, random_state=self.random_state)
        results = cross_val_score(clf, res_x, res_y, cv=kfold)
        y_pred = cross_val_predict(clf, res_x, self.y, cv=10)
        print('{} - {} - XGBoost Accuracy: {:.2f}% (+/- {:.2f}'.format(title, label, results.mean() * 100,
                                                                       results.std() * 100))
        self.visualize.confusion_matrix(res_y, y_pred, '{} - {} - Label {}'.format(title, clf.__class__.__name__,
                                                                                   label))


sampling = Sampling()
