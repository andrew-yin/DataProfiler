import warnings
from collections import defaultdict
from operator import itemgetter

import numpy as np

from . import BaseColumnProfiler
from .profiler_options import CategoricalOptions
from . import utils


class CategoricalColumn(BaseColumnProfiler):
    """
    Categorical column profile subclass of BaseColumnProfiler. Represents a
    column int the dataset which is a categorical column.
    """

    type = "category"

    # If total number of unique values in a column is less than this value,
    # that column is classified as a categorical column.
    _MAXIMUM_UNIQUE_VALUES_TO_CLASSIFY_AS_CATEGORICAL = 10

    # Default value that determines if a given col is categorical or not.
    _CATEGORICAL_THRESHOLD_DEFAULT = 0.2

    def __init__(self, name, options=None):
        """
        Initialization of column base properties and itself.

        :param name: Name of data
        :type name: String
        """
        if options and not isinstance(options, CategoricalOptions):
            raise ValueError("CategoricalColumn parameter 'options' must be of"
                             " type CategoricalOptions.")
        super(CategoricalColumn, self).__init__(name)
        self._categories = defaultdict(int)
        self.__calculations = {}
        self._filter_properties_w_options(self.__calculations, options)
        self._top_k_categories = None
        if options:
            self._top_k_categories = options.top_k_categories

    def __add__(self, other):
        """
        Merges the properties of two CategoricalColumn profiles

        :param self: first profile
        :param other: second profile
        :type self: CategoricalColumn
        :type other: CategoricalColumn
        :return: New CategoricalColumn merged profile
        """
        if not isinstance(other, CategoricalColumn):
            raise TypeError("Unsupported operand type(s) for +: "
                            "'CategoricalColumn' and '{}'".format(
                                other.__class__.__name__))

        merged_profile = CategoricalColumn(None)
        merged_profile._categories = \
            utils.add_nested_dictionaries(self._categories, other._categories)
        BaseColumnProfiler._add_helper(merged_profile, self, other)
        self._merge_calculations(merged_profile.__calculations,
                                 self.__calculations,
                                 other.__calculations)
        return merged_profile

    def diff(self, other_profile, options=None):
        """
        Finds the differences for CategoricalColumns.

        :param other_profile: profile to find the difference with
        :type other_profile: CategoricalColumn
        :return: the CategoricalColumn differences
        :rtype: dict
        """
        differences = super().diff(other_profile, options)

        differences["categorical"] = \
            utils.find_diff_of_strings_and_bools(self.is_match, 
                                                 other_profile.is_match)

        differences["statistics"] = dict([
                ('unique_count', utils.find_diff_of_numbers(
                    len(self.categories),
                    len(other_profile.categories))),
                ('unique_ratio', utils.find_diff_of_numbers(
                    self.unique_ratio,
                    other_profile.unique_ratio)),
            ])

        # These stats are only diffed if both profiles are categorical
        if self.is_match and other_profile.is_match:
            differences["chi2-test"] = self._perform_chi_squared_test(
                self._categories, other_profile._categories
            )
            differences["statistics"]['categories'] = \
                utils.find_diff_of_lists_and_sets(self.categories,
                                                  other_profile.categories)
            differences["statistics"]['gini_impurity'] = \
                utils.find_diff_of_numbers(self.gini_impurity,
                                           other_profile.gini_impurity)
            differences["statistics"]['unalikeability'] = \
                utils.find_diff_of_numbers(self.unalikeability,
                                           other_profile.unalikeability)
            cat_count1 = dict(sorted(self._categories.items(),
                                     key=itemgetter(1),
                                     reverse=True))
            cat_count2 = dict(sorted(other_profile._categories.items(),
                                     key=itemgetter(1),
                                     reverse=True))

            differences["statistics"]['categorical_count'] = \
                utils.find_diff_of_dicts(cat_count1, cat_count2)

        return differences

    @staticmethod
    def _perform_chi_squared_test(categories1, categories2):
        """
        Performs a Chi Squared test for homogeneity between two groups.

        :param categories1: Categories and respective counts of the first group
        :type categories1: dict
        :param categories2: Categories and respective counts of the second group
        :type categories2: dict
        :return: Results of the chi squared test
        :rtype: dict
        """
        results = {
            "chi2-statistic": None,
            "df": None,
            "p-value": None
        }


        combined_cats = list(set(categories1.keys()).union(set(categories2.keys())))
        num_cats = len(combined_cats)
        if len(combined_cats) < 1:
            warnings.warn("Insufficient number of categories. "
                          "Chi-squared test cannot be performed.", RuntimeWarning)
            return results

        # Calculate degrees of freedom
        # df = (rows - 1) * (cols - 1), in the case of two groups reduces to cols - 1
        df = num_cats - 1
        results["df"] = df

        cat_counts1 = [categories1[cat] if cat in categories1 else 0
                       for cat in combined_cats]
        cat_counts2 = [categories2[cat] if cat in categories2 else 0
                       for cat in combined_cats]
        observed = [cat_counts1, cat_counts2]
        row_sums = [sum(cat_counts1), sum(cat_counts2)]
        col_sums = [cat_counts1[i] + cat_counts2[i] for i in range(0, len(combined_cats))]
        total = sum(row_sums)

        # If a zero is found in either row or col sums, then an expected count will be
        # zero. This means the chi2-statistic and p-value are infinity and zero,
        # so calculation can be skipped.
        if 0 in row_sums or 0 in col_sums:
            results["chi2-statistic"] = np.inf
            results["p-value"] = 0
            return results

        # Calculate expected counts
        expected = [[None] * num_cats, [None] * num_cats]
        for i in range(0, len(row_sums)):
            expected.append([])
            for j in range(0, len(col_sums)):
                expected[i][j] = row_sums[i] * col_sums[j] / total

        # Calculate chi-sq statistic
        chi2_statistic = 0
        for i in range(0, len(observed)):
            for j in range(0, len(observed[i])):
                chi2_statistic += \
                    (observed[i][j] - expected[i][j]) ** 2 / expected[i][j]
        results["chi2-statistic"] = chi2_statistic

        try:
            import scipy.stats
        except ImportError:
            # Failed, so we return the stats but don't perform the test
            warnings.warn("Could not import necessary statistical packages. "
                          "To successfully perform the chi-squared test, please run 'pip "
                          "install scipy.' Test results will be incomplete.",
                          RuntimeWarning)
            return results

        # Calculate p-value, i.e. P(X > chi2_statistic)
        p_value = 1 - scipy.stats.chi2(df).cdf(chi2_statistic)
        results["p-value"] = p_value

        return results

    @property
    def profile(self):
        """
        Property for profile. Returns the profile of the column.
        For categorical_count, it will display the top k categories most
        frequently occurred in descending order.
        """

        profile = dict(
            categorical=self.is_match,
            statistics=dict([
                ('unique_count', len(self.categories)),
                ('unique_ratio', self.unique_ratio),
            ]),
            times=self.times
        )
        if self.is_match:
            profile["statistics"]['categories'] = self.categories
            profile["statistics"]['gini_impurity'] = self.gini_impurity
            profile["statistics"]['unalikeability'] = self.unalikeability
            profile["statistics"]['categorical_count'] = dict(
                sorted(self._categories.items(), key=itemgetter(1),
                       reverse=True)[:self._top_k_categories])
        return profile

    @property
    def categories(self):
        """
        Property for categories.
        """
        return list(self._categories.keys())

    @property
    def unique_ratio(self):
        """
        Property for unique_ratio. Returns ratio of unique 
        categories to sample_size
        """
        unique_ratio = 1.0
        if self.sample_size:
            unique_ratio = len(self.categories) / self.sample_size
        return unique_ratio

    @property
    def is_match(self):
        """
        Property for is_match. Returns true if column is categorical.
        """
        is_match = False
        unique = len(self._categories)
        if unique <= self._MAXIMUM_UNIQUE_VALUES_TO_CLASSIFY_AS_CATEGORICAL:
            is_match = True
        elif self.sample_size \
                and self.unique_ratio <= self._CATEGORICAL_THRESHOLD_DEFAULT:
            is_match = True
        return is_match

    @BaseColumnProfiler._timeit(name="categories")
    def _update_categories(self, df_series, prev_dependent_properties=None, 
                           subset_properties=None):
        """
        Check whether column corresponds to category type and adds category
        parameters if it is.

        :param prev_dependent_properties: Contains all the previous properties
        that the calculations depend on.
        :type prev_dependent_properties: dict
        :param subset_properties: Contains the results of the properties of the
        subset before they are merged into the main data profile.
        :type subset_properties: dict
        :param df_series: Data to be profiled
        :type df_series: pandas.DataFrame
        :return: None
        """
        category_count = df_series.value_counts(dropna=False).to_dict()
        self._categories = utils.add_nested_dictionaries(self._categories,
                                                         category_count)

    def _update_helper(self, df_series_clean, profile):
        """
        Method for updating the column profile properties with a cleaned
        dataset and the known profile of the dataset.

        :param df_series_clean: df series with nulls removed
        :type df_series_clean: pandas.core.series.Series
        :param profile: categorical profile dictionary
        :type profile: dict
        :return: None
        """
        self._update_column_base_properties(profile)

    def update(self, df_series):
        """
        Updates the column profile.

        :param df_series: Data to profile.
        :type df_series: pandas.core.series.Series
        :return: None
        """
        if len(df_series) == 0:
            return self

        profile = dict(
            sample_size=len(df_series)
        )
        CategoricalColumn._update_categories(self, df_series)
        BaseColumnProfiler._perform_property_calcs(
            self, self.__calculations, df_series=df_series,
            prev_dependent_properties={}, subset_properties=profile)

        self._update_helper(df_series, profile)

        return self

    @property
    def gini_impurity(self):
        """
        Property for Gini Impurity. Gini Impurity is a way to calculate
        likelihood of an incorrect classification of a new instance of
        a random variable.

        G = Σ(i=1; J): P(i) * (1 - P(i)), where i is the category classes.
        We are traversing through categories and calculating with the column

        :return: None or Gini Impurity probability
        """
        if self.sample_size == 0:
            return None
        gini_sum = 0
        for i in self._categories:
            gini_sum += (self._categories[i]/self.sample_size) * \
                         (1 - (self._categories[i]/self.sample_size))
        return gini_sum

    @property
    def unalikeability(self):
        """
        Property for Unlikeability. Unikeability checks for
        "how often observations differ from one another"
        Reference: Perry, M. and Kader, G. Variation as Unalikeability.
        Teaching Statistics, Vol. 27, No. 2 (2005), pp. 58-60.

        U = Σ(i=1,n)Σ(j=1,n): (Cij)/(n**2-n)
        Cij = 1 if i!=j, 0 if i=j

        :return: None or unlikeability probability
        """

        if self.sample_size == 0:
            return None
        elif self.sample_size == 1:
            return 0
        unalike_sum = 0
        for category in self._categories:
            unalike_sum += (self.sample_size - self._categories[category]) * \
                           self._categories[category]
        unalike = unalike_sum / (self.sample_size ** 2 - self.sample_size)
        return unalike
