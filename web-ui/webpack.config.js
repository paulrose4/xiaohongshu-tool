const { merge } = require('webpack-merge');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const ReactScriptsConfig = require('react-scripts/config/webpack.config');

module.exports = merge(ReactScriptsConfig, {
  plugins: [
    new HtmlWebpackPlugin({
      template: './public/index.html',
      filename: 'index.html',
    }),
  ],
});