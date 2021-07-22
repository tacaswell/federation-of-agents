import tensorflow as tf
import numpy as np
from federation.xca import XCACompanion
from federation.utils.transforms import default_transform_factory
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from IPython import display
from pathlib import Path
from xca.ml.tf_models import VAE


class VAECompanion(XCACompanion):
    def __init__(
        self,
        *,
        encoder_path,
        decoder_path,
        model_tth,
        exp_tth,
        coordinate_transform=None,
        ax=None,
        latent_dims=(0, 1),
        **kwargs,
    ):
        """

        Parameters
        ----------
        model_path: str, Path
        model_tth_: array
            Model 2-theta linspace
        exp_tth: array
            Experimental 2-theta linspace
        coordinate_transform: Callable
            Optional transformation for independent variables in tell.
            Useful for converting "scientific" space coordinates to less interpretable or reduced
            "beamline" space coordinates.
        latent_dims: list, tuple, stride of 2
            Latent dimensions of interest
        kwargs
        """
        super().__init__(**kwargs)
        self.encoder_path = Path(encoder_path).expanduser().absolute()
        self.decoder_path = Path(decoder_path).expanduser().absolute()
        self.model_name = (
            f"VAE from {self.encoder_path.stem} to {self.decoder_path.stem}"
        )
        self.model = VAE(
            encoder=tf.keras.models.load_model(str(self.encoder_path)),
            decoder=tf.keras.model.load_model(str(self.decoder_path)),
        )
        self.model_tth = model_tth
        self.exp_tth = exp_tth
        if coordinate_transform is None:
            self.coordinate_transform = default_transform_factory()
        else:
            self.coordinate_transform = coordinate_transform
        self.latent_dim_1 = latent_dims[0]
        self.latent_dim_2 = latent_dims[1]
        self.dependent_log_sigma = None
        self.dependent_reconstruction_error = None
        if ax is None:
            self.fig, self.ax = plt.subplots()
        else:
            self.ax = ax
            self.fig = ax.figure

    def predict(self, intensity):
        """
        Get XCA model prediction from intensity

        Parameters
        ----------
        intensity: array
            1-D array of intensity

        Returns
        -------
        z_mean
        z_log_sigma
        reconstruction_error

        """
        X = self.preprocess(self.exp_tth, intensity)
        X = tf.convert_to_tensor(X, dtype=tf.float32)
        output = self.model(X, training=False)
        return (
            output["z_mean"],
            output["z_log_sigma"],
            self.model.reconstruction_loss(X, output["reconstruction"]),
        )

    def tell(self, x, y):
        """
        Tell XCA about something new
        Parameters
        ----------
        x: These are the interesting parameters
        y: This should be the I(Q) shape (1, n_datapoints)

        Returns
        -------
        """
        ys = np.reshape(y, (1, -1))
        xs = np.reshape(x, (1, -1))
        self.tell_many(xs, ys)

    def tell_many(self, xs, ys):
        """
        Tell XCA about many new things
        Parameters
        ----------
        xs: These are the interesting parameters, they get converted to  space via a transform
        ys: list, arr
            This should be a list length m of the Q/I(Q) shape (n, 2)

        Returns
        -------

        """
        new_independents = list()
        for i in range(xs.shape[0]):
            new_independents.append(self.coordinate_transform.forward(*xs[i, :]))
        X = np.array(ys)
        z_means, z_log_sigmas, reconstruction_errors = self.predict(X)
        if self.independent is None:
            self.independent = np.array(new_independents)
            self.dependent = np.array(z_means)
            self.dependent_log_sigma = np.array(z_log_sigmas)
            self.dependent_reconstruction_error = np.array(reconstruction_errors)
        else:
            self.independent = np.vstack([self.independent, new_independents])
            self.dependent = np.vstack([self.dependent, z_means])
            self.dependent_log_sigma = np.vstack(
                [self.dependent_log_sigma, z_log_sigmas]
            )
            self.dependent_reconstruction_error = np.vstack(
                [self.dependent_reconstruction_error, reconstruction_errors]
            )

    def ask(self):
        raise NotImplementedError

    def prime_plot(self, X, labels):
        """
        Primes plot with previous data for reference.
        Makes assumptions about the labels. If float values, continuous colors are used.
        Otherwise, a categorical color scheme is used.

        Parameters
        ----------
        X
        labels

        Returns
        -------

        """
        # Clear plot
        self.ax.cla()

        z_mean, _, _ = self.predict(X)
        if isinstance(labels[0], float):
            self.ax.scatter(
                z_mean[:, self.latent_dim_1],
                z_mean[:, self.latent_dim_2],
                c=labels,
                cmap="RdBu_r",
                norm=Normalize(np.min(labels), np.max(labels)),
            )
        else:
            for label in labels:
                mask = [label == y for y in labels]
                self.ax.scatter(
                    z_mean[mask, self.latent_dim_1],
                    z_mean[mask, self.latent_dim_2],
                    label=label,
                )

    def update_plot(self, independent=None):
        """

        Parameters
        ----------
        independent: ndarray
            Optional independent variable to choose from for categortical

        Returns
        -------

        """

        if independent is None:
            idx = -1
        else:
            idx = np.argwhere(
                self.coordinate_transform.forward(*independent) == self.independent
            )
        z_mean = self.dependent[idx, :]
        z_log_sigma = self.dependent_log_sigma[idx, :]
        size = self.dependent_reconstruction_error[idx] / np.max(
            self.dependent_reconstruction_error
        )
        self.ax.errorbar(
            z_mean[self.latent_dim_1],
            z_mean[self.latent_dim_2],
            xerr=np.exp(z_log_sigma[self.latent_dim_1]),
            yerr=np.exp(z_log_sigma[self.latent_dim_2]),
            fmt="o",
            s=size,
        )

        # Polish the rest off
        self.fig.patch.set_facecolor("white")
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        display.clear_output(wait=True)
        display.display(self.fig)

    def observe(self, *args, **kwargs):
        self.update_plot(**kwargs)
