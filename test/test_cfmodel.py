import numpy as np
import pandas as pd
import pytest
from tensorflow import Graph, Session

from carla.data.catalog import OnlineCatalog
from carla.models.catalog import MLModelCatalog
from carla.models.negative_instances import predict_negative_instances
from carla.recourse_methods.catalog.actionable_recourse import ActionableRecourse
from carla.recourse_methods.catalog.cchvae import CCHVAE
from carla.recourse_methods.catalog.cem import CEM
from carla.recourse_methods.catalog.clue import Clue
from carla.recourse_methods.catalog.crud import CRUD
from carla.recourse_methods.catalog.dice import Dice
from carla.recourse_methods.catalog.face import Face
from carla.recourse_methods.catalog.feature_tweak import FeatureTweak
from carla.recourse_methods.catalog.focus import FOCUS
from carla.recourse_methods.catalog.growing_spheres.model import GrowingSpheres
from carla.recourse_methods.catalog.revise import Revise
from carla.recourse_methods.catalog.wachter import Wachter
from carla.recourse_methods.catalog.geco import GeCo

testmodel = ["ann", "linear"]


@pytest.mark.parametrize("backend", ["xgboost", "sklearn"])
def test_feature_tweak_get_counterfactuals(backend):

    data_name = "adult"
    data = OnlineCatalog(data_name)
    model = MLModelCatalog(data, "forest", backend, load_online=False)
    model.train(max_depth=2, n_estimators=5)

    hyperparams = {
        "eps": 0.1,
    }

    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:5]

    feature_tweak = FeatureTweak(model, hyperparams)
    cfs = feature_tweak.get_counterfactuals(test_factual)

    assert test_factual[data.continuous].shape == cfs.shape
    assert isinstance(cfs, pd.DataFrame)


@pytest.mark.parametrize("backend", ["sklearn", "xgboost"])
def test_focus_get_counterfactuals(backend):

    data_name = "adult"
    data = OnlineCatalog(data_name)
    model = MLModelCatalog(data, "forest", backend, load_online=False)
    model.train(max_depth=2, n_estimators=5)

    hyperparams = {
        "optimizer": "adam",
        "lr": 0.001,
        "n_class": 2,
        "n_iter": 1000,
        "sigma": 1.0,
        "temperature": 1.0,
        "distance_weight": 0.01,
        "distance_func": "l1",
    }

    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:5]

    focus = FOCUS(model, hyperparams)
    cfs = focus.get_counterfactuals(test_factual)

    assert test_factual[data.continuous].shape == cfs.shape
    assert isinstance(cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_dice_get_counterfactuals(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model_tf = MLModelCatalog(data, model_type)

    # get factuals
    factuals = predict_negative_instances(model_tf, data.df)

    hyperparams = {
        "num": 1,
        "desired_class": 1,
        "posthoc_sparsity_param": 0.1,
    }
    test_factual = factuals.iloc[:5]

    df_cfs = Dice(model_tf, hyperparams).get_counterfactuals(factuals=test_factual)

    cfs = model_tf.get_ordered_features(df_cfs)

    assert test_factual.shape[0] == cfs.shape[0]
    assert (cfs.columns == model_tf.feature_input_order).all()
    assert isinstance(cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_ar_get_counterfactual(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)
    model_tf = MLModelCatalog(data, model_type)

    coeffs, intercepts = None, None

    if model_type == "linear":
        # get weights and bias of linear layer for negative class 0
        coeffs_neg = model_tf.raw_model.layers[0].get_weights()[0][:, 0]
        intercepts_neg = np.array(model_tf.raw_model.layers[0].get_weights()[1][0])

        # get weights and bias of linear layer for positive class 1
        coeffs_pos = model_tf.raw_model.layers[0].get_weights()[0][:, 1]
        intercepts_pos = np.array(model_tf.raw_model.layers[0].get_weights()[1][1])

        coeffs = -(coeffs_neg - coeffs_pos)
        intercepts = -(intercepts_neg - intercepts_pos)

    # get factuals
    factuals = predict_negative_instances(model_tf, data.df)
    test_factual = factuals.iloc[:5]

    # get counterfactuals
    hyperparams = {"fs_size": 150}
    cfs = ActionableRecourse(
        model_tf, hyperparams, coeffs=coeffs, intercepts=intercepts
    ).get_counterfactuals(test_factual)

    assert test_factual.shape[0] == cfs.shape[0]
    assert (cfs.columns == model_tf.feature_input_order).all()
    assert isinstance(cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_cem_get_counterfactuals(model_type):
    data_name = "adult"
    data = OnlineCatalog(data_name=data_name)

    hyperparams_cem = {
        "batch_size": 1,
        "kappa": 0.1,
        "init_learning_rate": 1e-2,
        "binary_search_steps": 9,
        "max_iterations": 100,
        "initial_const": 10,
        "beta": 0.9,
        "gamma": 0.0,
        "mode": "PN",
        "num_classes": 2,
        "data_name": data_name,
        "ae_params": {"hidden_layer": [20, 10, 7], "train_ae": True, "epochs": 5},
    }

    graph = Graph()
    with graph.as_default():
        ann_sess = Session()
        with ann_sess.as_default():
            model_ann = MLModelCatalog(
                data=data, model_type=model_type, encoding_method="Binary"
            )

            factuals = predict_negative_instances(model_ann, data.df)
            test_factuals = factuals.iloc[:5]

            recourse = CEM(
                sess=ann_sess,
                mlmodel=model_ann,
                hyperparams=hyperparams_cem,
            )

            counterfactuals_df = recourse.get_counterfactuals(factuals=test_factuals)

    assert (
        counterfactuals_df.shape == model_ann.get_ordered_features(test_factuals).shape
    )
    assert isinstance(counterfactuals_df, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_cem_vae(model_type):
    data_name = "adult"
    data = OnlineCatalog(data_name=data_name)

    hyperparams_cem = {
        "batch_size": 1,
        "kappa": 0.1,
        "init_learning_rate": 1e-2,
        "binary_search_steps": 9,
        "max_iterations": 100,
        "initial_const": 10,
        "beta": 0.0,
        "gamma": 6.0,
        "mode": "PN",
        "num_classes": 2,
        "data_name": data_name,
        "ae_params": {"hidden_layer": [20, 10, 7], "train_ae": True, "epochs": 5},
    }

    graph = Graph()
    with graph.as_default():
        ann_sess = Session()
        with ann_sess.as_default():
            model_ann = MLModelCatalog(
                data=data, model_type=model_type, encoding_method="Binary"
            )

            factuals = predict_negative_instances(model_ann, data.df)
            test_factuals = factuals.iloc[:5]

            recourse = CEM(
                sess=ann_sess,
                mlmodel=model_ann,
                hyperparams=hyperparams_cem,
            )

            counterfactuals_df = recourse.get_counterfactuals(factuals=test_factuals)

    assert (
        counterfactuals_df.shape == model_ann.get_ordered_features(test_factuals).shape
    )
    assert isinstance(counterfactuals_df, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_face_get_counterfactuals(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model_tf = MLModelCatalog(data, model_type)
    # get factuals
    factuals = predict_negative_instances(model_tf, data.df)
    test_factual = factuals.iloc[:5]

    # Test for knn mode
    hyperparams = {"mode": "knn", "fraction": 0.05}
    face = Face(model_tf, hyperparams)
    df_cfs = face.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model_tf.feature_input_order).all()

    # Test for epsilon mode
    face.mode = "epsilon"
    df_cfs = face.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model_tf.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_growing_spheres(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model_tf = MLModelCatalog(data, model_type)
    # get factuals
    factuals = predict_negative_instances(model_tf, data.df)
    test_factual = factuals.iloc[:5]

    gs = GrowingSpheres(model_tf)
    df_cfs = gs.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model_tf.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_clue(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model = MLModelCatalog(data, model_type, backend="pytorch")
    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:20]

    hyperparams = {
        "data_name": data_name,
        "train_vae": True,
        "width": 10,
        "depth": 2,
        "latent_dim": 8,
        "batch_size": 64,
        "epochs": 1,  # Only for test purpose, else at least 10 epochs
        "lr": 1e-3,
        "early_stop": 10,
    }
    df_cfs = Clue(data, model, hyperparams).get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_wachter(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model = MLModelCatalog(data, model_type, backend="pytorch")
    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:10]

    hyperparams = {"loss_type": "MSE", "binary_cat_features": True, "y_target": [1]}
    df_cfs = Wachter(model, hyperparams).get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_revise(model_type):
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model = MLModelCatalog(data, model_type, backend="pytorch")
    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:5]

    vae_params = {
        "layers": [len(model.feature_input_order), 512, 256, 8],
        "train": True,
        "lambda_reg": 1e-6,
        "epochs": 1,
        "lr": 1e-3,
        "batch_size": 32,
    }

    hyperparams = {
        "data_name": data_name,
        "lambda": 0.5,
        "optimizer": "adam",
        "lr": 0.1,
        "max_iter": 1500,
        "target_class": [0, 1],
        "vae_params": vae_params,
        "binary_cat_features": True,
    }

    revise = Revise(model, data, hyperparams)
    df_cfs = revise.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_cchvae(model_type):
    data_name = "compas"
    data = OnlineCatalog(data_name)

    model = MLModelCatalog(data, model_type, backend="pytorch")
    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:5]

    hyperparams = {
        "data_name": data_name,
        "n_search_samples": 100,
        "p_norm": 1,
        "step": 0.1,
        "max_iter": 1000,
        "clamp": True,
        "binary_cat_features": True,
        "vae_params": {
            "layers": [len(model.feature_input_order), 512, 256, 8],
            "train": True,
            "lambda_reg": 1e-6,
            "epochs": 5,
            "lr": 1e-3,
            "batch_size": 32,
        },
    }

    cchvae = CCHVAE(model, hyperparams)
    df_cfs = cchvae.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model.feature_input_order).all()
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_crud(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model = MLModelCatalog(data, model_type, backend="pytorch")
    # get factuals
    factuals = predict_negative_instances(model, data.df)
    test_factual = factuals.iloc[:5]

    hyperparams = {
        "data_name": data_name,
        "target_class": [0, 1],
        "lambda_param": 0.001,
        "optimizer": "RMSprop",
        "lr": 0.008,
        "max_iter": 2000,
        "binary_cat_features": True,
        "vae_params": {
            "layers": [len(model.feature_input_order), 16, 8],
            "train": True,
            "epochs": 5,
            "lr": 1e-3,
            "batch_size": 32,
        },
    }

    crud = CRUD(model, hyperparams)
    df_cfs = crud.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert isinstance(df_cfs, pd.DataFrame)


@pytest.mark.parametrize("model_type", testmodel)
def test_geco(model_type):
    # Build data and mlmodel
    data_name = "adult"
    data = OnlineCatalog(data_name)

    model_tf = MLModelCatalog(data, model_type)
    # get factuals
    factuals = predict_negative_instances(model_tf, data.df)
    test_factual = factuals.iloc[:5]

    geco = GeCo(model_tf)
    df_cfs = geco.get_counterfactuals(test_factual)

    assert test_factual.shape[0] == df_cfs.shape[0]
    assert (df_cfs.columns == model_tf.feature_input_order + [data.target]).all()
    assert isinstance(df_cfs, pd.DataFrame)
